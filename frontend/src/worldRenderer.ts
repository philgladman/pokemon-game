import * as THREE from "three";

import { AssetFactory, requireAppearance } from "./assetFactory";
import type { MapDefinition, Position, SessionSnapshot } from "./types";

const MOVE_DURATION_MS = 140;

export class WorldRenderer {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100);
  private readonly worldGroup = new THREE.Group();
  private readonly assetFactory = new AssetFactory();
  private player: THREE.Object3D | null = null;
  private playerAppearance: string | null = null;
  private currentMapId: string | null = null;
  private moveStartedAt = 0;
  private moveFrom = new THREE.Vector3();
  private moveTo = new THREE.Vector3();

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.scene.background = new THREE.Color("#b8dced");
    this.scene.add(this.worldGroup);

    const ambient = new THREE.HemisphereLight("#ffffff", "#50705e", 2.2);
    this.scene.add(ambient);
    const sun = new THREE.DirectionalLight("#fff4dc", 2.8);
    sun.position.set(-8, 14, 6);
    sun.castShadow = true;
    this.scene.add(sun);

    window.addEventListener("resize", () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop((time) => this.render(time));
  }

  update(snapshot: SessionSnapshot): void {
    const mapChanged = snapshot.map.id !== this.currentMapId;
    if (mapChanged) {
      this.rebuildMap(snapshot.map, snapshot.asset_manifest);
      this.currentMapId = snapshot.map.id;
    }

    if (this.player === null || this.playerAppearance !== snapshot.player.appearance) {
      if (this.player !== null) {
        this.scene.remove(this.player);
        this.assetFactory.dispose(this.player);
      }
      const appearance = requireAppearance(snapshot.asset_manifest, snapshot.player.appearance);
      this.player = this.assetFactory.create(appearance);
      this.playerAppearance = snapshot.player.appearance;
      this.scene.add(this.player);
    }

    const target = this.toWorld(snapshot.map, snapshot.player.position, 0.48);
    if (mapChanged) {
      this.player.position.copy(target);
      this.moveFrom.copy(target);
      this.moveTo.copy(target);
    } else if (!target.equals(this.moveTo)) {
      this.moveFrom.copy(this.player.position);
      this.moveTo.copy(target);
      this.moveStartedAt = performance.now();
    }
    this.player.rotation.y = this.facingRotation(snapshot.player.facing);
  }

  private rebuildMap(
    map: MapDefinition,
    manifest: SessionSnapshot["asset_manifest"],
  ): void {
    this.disposeChildren(this.worldGroup);
    for (let y = 0; y < map.height; y += 1) {
      for (let x = 0; x < map.width; x += 1) {
        const tileId = map.tiles[y]?.[x];
        const tile = tileId === undefined ? undefined : map.tile_definitions[tileId];
        if (tile === undefined) {
          throw new Error(`Missing tile definition at (${x}, ${y})`);
        }
        const object = this.assetFactory.create(requireAppearance(manifest, tile.appearance));
        object.position.copy(this.toWorld(map, { x, y }, 0));
        this.worldGroup.add(object);
      }
    }

    for (const npc of map.npcs) {
      const character = this.assetFactory.create(requireAppearance(manifest, npc.appearance));
      character.position.copy(this.toWorld(map, npc.position, 0.48));
      character.rotation.y = this.facingRotation(npc.facing);
      this.worldGroup.add(character);
    }

    this.camera.position.set(0, Math.max(13, map.height * 0.85), map.height * 0.72);
    this.camera.lookAt(0, 0, 0);
  }

  private toWorld(map: MapDefinition, position: Position, height: number): THREE.Vector3 {
    return new THREE.Vector3(position.x - map.width / 2 + 0.5, height, position.y - map.height / 2 + 0.5);
  }

  private facingRotation(facing: string): number {
    return { north: Math.PI, south: 0, west: -Math.PI / 2, east: Math.PI / 2 }[facing] ?? 0;
  }

  private resize(): void {
    const width = window.innerWidth;
    const height = window.innerHeight;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  private render(time: number): void {
    if (this.player !== null && !this.player.position.equals(this.moveTo)) {
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
