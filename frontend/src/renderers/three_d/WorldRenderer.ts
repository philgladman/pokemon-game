import * as THREE from "three";

import type {
  AppearanceDefinition,
  Direction,
  GameRenderer,
  MapDefinition,
  PresentationContext,
  Position,
  SessionSnapshot,
  ThreeDMapResources,
} from "../../types";
import { isAdjacentStep, MOVE_DURATION_MS } from "../../movement";
import { animateMovementCue, movementTrackState } from "../../scriptedMovement";
import { AssetFactory, requireAppearance } from "./AssetFactory";
import { ThreeDResourceLoader } from "./resources";

export class PlayerMotionAuthority {
  private scripted = false;

  observeSnapshot(hasPlayerCue: boolean): void {
    if (hasPlayerCue) this.scripted = true;
  }

  snapshotApplied(hasPlayerCue: boolean): void {
    this.scripted = hasPlayerCue;
  }

  normalInterpolationAllowed(): boolean {
    return !this.scripted;
  }
}

export class WorldRenderer implements GameRenderer {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100);
  private readonly worldGroup = new THREE.Group();
  private readonly assetFactory = new AssetFactory();
  private readonly resources = new ThreeDResourceLoader();
  private manifest: Record<string, AppearanceDefinition> | null = null;
  private latestSnapshot: SessionSnapshot | null = null;
  private player: THREE.Object3D | null = null;
  private playerAppearance: string | null = null;
  private currentMapId: string | null = null;
  private moveStartedAt = 0;
  private lastPlayerPosition: Position | null = null;
  private readonly moveFrom = new THREE.Vector3();
  private readonly moveTo = new THREE.Vector3();
  private actorSignature = "";
  private readonly actors = new Map<string, THREE.Object3D>();
  private readonly playerMotionAuthority = new PlayerMotionAuthority();

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.scene.background = new THREE.Color("#b8dced");
    this.scene.add(this.worldGroup);

    this.scene.add(new THREE.HemisphereLight("#ffffff", "#50705e", 2.2));
    const sun = new THREE.DirectionalLight("#fff4dc", 2.8);
    sun.position.set(-8, 14, 6);
    sun.castShadow = true;
    this.scene.add(sun);

    window.addEventListener("resize", () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop((time) => this.render(time));
  }

  async update(
    snapshot: SessionSnapshot,
    _presentation: PresentationContext,
  ): Promise<void> {
    const previousHadCue = this.latestSnapshot?.movement_cue !== null
      && this.latestSnapshot?.movement_cue !== undefined;
    const hasPlayerCue =
      snapshot.movement_cue?.tracks.some((track) => track.actor_id === "player") ?? false;
    this.playerMotionAuthority.observeSnapshot(hasPlayerCue);
    this.latestSnapshot = snapshot;
    try {
      const [manifest, mapResources] = await Promise.all([
        this.resources.manifest(),
        this.resources.map(snapshot.map.id),
      ]);
      if (this.latestSnapshot !== snapshot || snapshot.map.id !== mapResources.map_id) return;
      this.manifest = manifest;
      this.applySnapshot(snapshot, mapResources, previousHadCue);
      this.playerMotionAuthority.snapshotApplied(hasPlayerCue);
      this.renderer.render(this.scene, this.camera);
      if (snapshot.movement_cue !== null) {
        await animateMovementCue(snapshot.movement_cue, (elapsed) => {
          for (const track of snapshot.movement_cue?.tracks ?? []) {
            const state = movementTrackState(track, elapsed);
            const object = track.actor_id === "player" ? this.player : this.actors.get(track.actor_id);
            object?.position.copy(this.toWorld(snapshot.map, state.position, 0.48));
            if (object !== undefined && object !== null && state.facing !== null) {
              object.rotation.y = facingRotation(state.facing);
            }
            if (track.actor_id === "player") {
              this.camera.lookAt(object?.position ?? new THREE.Vector3());
            }
          }
          this.renderer.render(this.scene, this.camera);
        });
      }
    } catch (error: unknown) {
      console.error("Unable to update the 3D renderer.", error);
      throw error;
    }
  }

  private applySnapshot(
    snapshot: SessionSnapshot,
    resources: ThreeDMapResources,
    previousHadCue: boolean,
  ): void {
    const manifest = this.manifest;
    if (manifest === null) return;
    const signature = JSON.stringify(snapshot.map.actors);
    const mapChanged = snapshot.map.id !== this.currentMapId;
    if (mapChanged || signature !== this.actorSignature) {
      this.rebuildMap(snapshot.map, resources, manifest);
      this.currentMapId = snapshot.map.id;
      this.actorSignature = signature;
    }

    const playerChanged =
      this.player === null || this.playerAppearance !== resources.player_appearance;
    if (playerChanged) {
      if (this.player !== null) {
        this.scene.remove(this.player);
        this.assetFactory.dispose(this.player);
      }
      this.player = this.assetFactory.create(
        requireAppearance(manifest, resources.player_appearance),
      );
      this.playerAppearance = resources.player_appearance;
      this.scene.add(this.player);
    }
    const player = this.player;
    if (player === null) throw new Error("Player creation failed");

    const target = this.toWorld(snapshot.map, snapshot.player.position, 0.48);
    if (
      mapChanged ||
      playerChanged ||
      previousHadCue ||
      this.lastPlayerPosition === null ||
      !isAdjacentStep(this.lastPlayerPosition, snapshot.player.position)
    ) {
      player.position.copy(target);
      this.moveFrom.copy(target);
      this.moveTo.copy(target);
    } else if (!target.equals(this.moveTo)) {
      this.moveFrom.copy(player.position);
      this.moveTo.copy(target);
      this.moveStartedAt = performance.now();
    }
    this.lastPlayerPosition = snapshot.player.position;
    player.rotation.y = facingRotation(snapshot.player.facing);
  }

  private rebuildMap(
    map: MapDefinition,
    resources: ThreeDMapResources,
    manifest: Record<string, AppearanceDefinition>,
  ): void {
    this.disposeChildren(this.worldGroup);
    this.actors.clear();
    for (let y = 0; y < map.height; y += 1) {
      for (let x = 0; x < map.width; x += 1) {
        const appearance = resources.tile_appearances[y]?.[x];
        if (appearance === undefined) {
          throw new Error(`Missing 3D tile resource at (${x}, ${y})`);
        }
        const object = this.assetFactory.create(requireAppearance(manifest, appearance));
        object.position.copy(this.toWorld(map, { x, y }, 0));
        this.worldGroup.add(object);
      }
    }

    for (const actor of map.actors.filter((candidate) => candidate.visible)) {
      const appearance = resources.npc_appearances[actor.id];
      if (appearance === undefined) {
        throw new Error(`Missing 3D appearance for actor ${actor.id}`);
      }
      const character = this.assetFactory.create(requireAppearance(manifest, appearance));
      character.position.copy(this.toWorld(map, actor.position, 0.48));
      character.rotation.y = facingRotation(actor.facing);
      this.worldGroup.add(character);
      this.actors.set(actor.id, character);
    }

    this.camera.position.set(0, Math.max(13, map.height * 0.85), map.height * 0.72);
    this.camera.lookAt(0, 0, 0);
  }

  private toWorld(map: MapDefinition, position: Position, height: number): THREE.Vector3 {
    return new THREE.Vector3(
      position.x - map.width / 2 + 0.5,
      height,
      position.y - map.height / 2 + 0.5,
    );
  }

  private resize(): void {
    const width = window.innerWidth;
    const height = window.innerHeight;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  private render(time: number): void {
    if (
      this.playerMotionAuthority.normalInterpolationAllowed()
      && this.player !== null
      && !this.player.position.equals(this.moveTo)
    ) {
      const progress = Math.min(1, (time - this.moveStartedAt) / MOVE_DURATION_MS);
      const eased = 1 - (1 - progress) ** 3;
      this.player.position.lerpVectors(this.moveFrom, this.moveTo, eased);
    }
    this.renderer.render(this.scene, this.camera);
  }

  private disposeChildren(group: THREE.Group): void {
    for (const child of [...group.children]) {
      this.assetFactory.dispose(child);
      group.remove(child);
    }
  }
}

function facingRotation(facing: Direction): number {
  return { north: Math.PI, south: 0, west: -Math.PI / 2, east: Math.PI / 2 }[facing];
}
