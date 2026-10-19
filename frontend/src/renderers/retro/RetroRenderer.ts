import type {
  Direction,
  GameRenderer,
  PresentationContext,
  RetroMapResources,
  SessionSnapshot,
  SourceAsset,
} from "../../types";
import {
  isAdjacentStep,
  MOVEMENT_ADVANCES,
  MOVE_DURATION_MS,
  movementAdvanceAt,
  pixelSteppedPosition,
} from "../../movement";

const VIEW_WIDTH = 160;
const VIEW_HEIGHT = 144;
const TILE_SIZE = 8;
const STEP_SIZE = 16;

export function viewportOrigin(
  mapWidth: number,
  mapHeight: number,
  playerX: number,
  playerY: number,
): { x: number; y: number } {
  const mapPixelsWide = mapWidth * STEP_SIZE;
  const mapPixelsHigh = mapHeight * STEP_SIZE;
  const desiredX = playerX * STEP_SIZE + STEP_SIZE / 2 - VIEW_WIDTH / 2;
  const desiredY = playerY * STEP_SIZE + STEP_SIZE / 2 - VIEW_HEIGHT / 2;
  return {
    x: Math.max(0, Math.min(desiredX, Math.max(0, mapPixelsWide - VIEW_WIDTH))),
    y: Math.max(0, Math.min(desiredY, Math.max(0, mapPixelsHigh - VIEW_HEIGHT))),
  };
}

export interface SpriteFrame {
  y: number;
  mirrored: boolean;
  walking: boolean;
  sourcePhase: SourceMovementPhase;
}

export type SourceMovementPhase = 0 | 1 | 2 | 3;
export type StandingPhase = 0 | 2;

export function nextStandingPhase(phase: StandingPhase): StandingPhase {
  return phase === 0 ? 2 : 0;
}

export function sourceMovementPhase(
  elapsedMs: number,
  startingPhase: StandingPhase = 0,
): SourceMovementPhase {
  const endingPhase = nextStandingPhase(startingPhase);
  const advance = movementAdvanceAt(elapsedMs);
  if (advance === MOVEMENT_ADVANCES) return endingPhase;
  if (advance < MOVEMENT_ADVANCES / 2) return startingPhase;
  return (startingPhase + 1) as 1 | 3;
}

export function spriteFrameForPhase(
  direction: Direction,
  sourcePhase: SourceMovementPhase,
): SpriteFrame {
  const standingRows: Record<Direction, number> = {
    south: 0,
    north: 16,
    west: 32,
    east: 32,
  };
  const walkingRows: Record<Direction, number> = {
    south: 48,
    north: 64,
    west: 80,
    east: 80,
  };
  const walking = sourcePhase === 1 || sourcePhase === 3;
  const flippedVerticalWalk =
    sourcePhase === 3 && (direction === "north" || direction === "south");
  return {
    y: walking ? walkingRows[direction] : standingRows[direction],
    mirrored: direction === "east" || flippedVerticalWalk,
    walking,
    sourcePhase,
  };
}

export function spriteFrameAtElapsed(
  direction: Direction,
  elapsedMs: number,
  startingPhase: StandingPhase = 0,
): SpriteFrame {
  return spriteFrameForPhase(direction, sourceMovementPhase(elapsedMs, startingPhase));
}

export function shouldAnimatePlayerMove(
  previousMapId: string,
  nextMapId: string,
  from: { x: number; y: number },
  to: { x: number; y: number },
  resourcesChanged = false,
): boolean {
  return previousMapId === nextMapId && !resourcesChanged && isAdjacentStep(from, to);
}

interface PlayerMotion {
  from: { x: number; y: number };
  to: { x: number; y: number };
  startedAt: number;
  startingPhase: StandingPhase;
}

export class SourceImages {
  private readonly images = new Map<string, HTMLImageElement>();
  private readonly loading = new Map<string, Promise<HTMLImageElement>>();
  private readonly transparentSprites = new Map<string, HTMLCanvasElement>();

  get(url: string): HTMLImageElement | undefined {
    return this.images.get(url);
  }

  sprite(url: string): HTMLCanvasElement | undefined {
    const existing = this.transparentSprites.get(url);
    if (existing !== undefined) return existing;
    const image = this.images.get(url);
    if (image === undefined) return undefined;
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (context === null) throw new Error("Canvas 2D is unavailable");
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    for (let offset = 0; offset < pixels.data.length; offset += 4) {
      if (pixels.data[offset]! > 245 && pixels.data[offset + 1]! > 245 && pixels.data[offset + 2]! > 245) {
        pixels.data[offset + 3] = 0;
      }
    }
    context.putImageData(pixels, 0, 0);
    this.transparentSprites.set(url, canvas);
    return canvas;
  }

  load(asset: SourceAsset): Promise<HTMLImageElement> {
    const loaded = this.images.get(asset.url);
    if (loaded !== undefined) return Promise.resolve(loaded);
    const pending = this.loading.get(asset.url);
    if (pending !== undefined) return pending;
    const request = new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      image.addEventListener("load", () => {
        this.images.set(asset.url, image);
        this.loading.delete(asset.url);
        resolve(image);
      });
      image.addEventListener("error", () => {
        this.loading.delete(asset.url);
        reject(new Error(`Unable to load ${asset.url}`));
      });
      image.src = asset.url;
    });
    this.loading.set(asset.url, request);
    return request;
  }
}

export class RetroRenderer implements GameRenderer {
  private readonly context: CanvasRenderingContext2D;
  private readonly images = new SourceImages();
  private snapshot: SessionSnapshot | null = null;
  private resources: RetroMapResources | null = null;
  private readonly resourceRequests = new Map<string, Promise<RetroMapResources>>();
  private resourceKey: string | null = null;
  private playerMotion: PlayerMotion | null = null;
  private animationFrame: number | null = null;
  private nextStepStartingPhase: StandingPhase = 0;
  private standingPhase: StandingPhase = 0;

  constructor(canvas: HTMLCanvasElement) {
    canvas.width = VIEW_WIDTH;
    canvas.height = VIEW_HEIGHT;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("Canvas 2D is unavailable");
    context.imageSmoothingEnabled = false;
    this.context = context;
  }

  async update(
    snapshot: SessionSnapshot,
    presentation: PresentationContext,
  ): Promise<void> {
    const previousSnapshot = this.snapshot;
    this.snapshot = snapshot;
    this.resources = this.resources?.map_id === snapshot.map.id ? this.resources : null;
    if (presentation.resetGait) {
      this.nextStepStartingPhase = 0;
      this.standingPhase = 0;
    }
    if (
      previousSnapshot !== null &&
      shouldAnimatePlayerMove(
        previousSnapshot.map.id,
        snapshot.map.id,
        previousSnapshot.player.position,
        snapshot.player.position,
      )
    ) {
      const startingPhase = this.nextStepStartingPhase;
      this.playerMotion = {
        from: previousSnapshot.player.position,
        to: snapshot.player.position,
        startedAt: performance.now(),
        startingPhase,
      };
      this.standingPhase = nextStandingPhase(startingPhase);
      this.nextStepStartingPhase = this.standingPhase;
      this.scheduleAnimation();
    } else {
      this.stopAnimation();
    }
    this.draw(snapshot);
    try {
      const resources = await this.loadResources(snapshot.map.id);
      const assets = [
        resources.tileset_asset,
        resources.player_asset,
        ...snapshot.map.npcs
          .filter((npc) => npc.visible)
          .map((npc) => resources.sprite_assets[npc.sprite])
          .filter((asset): asset is SourceAsset => asset !== undefined),
      ];
      await Promise.all(assets.map((asset) => this.images.load(asset)));
      if (this.snapshot !== snapshot) return;
      const nextResourceKey = this.resourcesKey(resources);
      if (this.resourceKey !== nextResourceKey) {
        this.resourceKey = nextResourceKey;
        this.stopAnimation();
      }
      this.resources = resources;
      this.draw(snapshot);
    } catch (error: unknown) {
      console.error(error);
      this.draw(snapshot);
      throw error;
    }
  }

  private draw(snapshot: SessionSnapshot, now = performance.now()): void {
    this.context.fillStyle = "#9bbc0f";
    this.context.fillRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
    const motion = this.playerMotion;
    const elapsed = motion === null ? MOVE_DURATION_MS : now - motion.startedAt;
    const playerPosition =
      motion === null
        ? snapshot.player.position
        : pixelSteppedPosition(motion.from, motion.to, elapsed);
    const playerFrame =
      motion === null
        ? spriteFrameForPhase(snapshot.player.facing, this.standingPhase)
        : spriteFrameAtElapsed(snapshot.player.facing, elapsed, motion.startingPhase);
    const origin = viewportOrigin(
      snapshot.map.width,
      snapshot.map.height,
      playerPosition.x,
      playerPosition.y,
    );
    this.drawMap(snapshot, origin.x, origin.y);
    const resources = this.resources;
    for (const npc of snapshot.map.npcs) {
      const asset = resources?.sprite_assets[npc.sprite];
      if (npc.visible && asset !== undefined) {
        this.drawSprite(asset, npc.position.x, npc.position.y, npc.facing, origin.x, origin.y);
      }
    }
    if (resources !== null) {
      this.drawSprite(
        resources.player_asset,
        playerPosition.x,
        playerPosition.y,
        snapshot.player.facing,
        origin.x,
        origin.y,
        playerFrame,
      );
    }
  }

  private drawMap(snapshot: SessionSnapshot, originX: number, originY: number): void {
    const graphics = this.resources;
    if (graphics === null || graphics.map_id !== snapshot.map.id) return;
    const tileset = this.images.get(graphics.tileset_asset.url);
    if (tileset === undefined) return;
    for (let y = 0; y < graphics.tile_ids.length; y += 1) {
      const screenY = y * TILE_SIZE - originY;
      if (screenY <= -TILE_SIZE || screenY >= VIEW_HEIGHT) continue;
      const row = graphics.tile_ids[y] ?? [];
      for (let x = 0; x < row.length; x += 1) {
        const screenX = x * TILE_SIZE - originX;
        if (screenX <= -TILE_SIZE || screenX >= VIEW_WIDTH) continue;
        const tileId = row[x]!;
        this.context.drawImage(
          tileset,
          (tileId % graphics.tiles_per_row) * graphics.tile_size,
          Math.floor(tileId / graphics.tiles_per_row) * graphics.tile_size,
          graphics.tile_size,
          graphics.tile_size,
          screenX,
          screenY,
          TILE_SIZE,
          TILE_SIZE,
        );
      }
    }
  }

  private loadResources(mapId: string): Promise<RetroMapResources> {
    const pending = this.resourceRequests.get(mapId);
    if (pending !== undefined) return pending;
    const request = fetch(`/api/renderers/retro/maps/${encodeURIComponent(mapId)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Unable to load retro resources for ${mapId}`);
        return (await response.json()) as RetroMapResources;
      })
      .catch((error: unknown) => {
        this.resourceRequests.delete(mapId);
        throw error;
      });
    this.resourceRequests.set(mapId, request);
    return request;
  }

  private drawSprite(
    asset: SourceAsset,
    x: number,
    y: number,
    facing: Direction,
    originX: number,
    originY: number,
    selectedFrame?: SpriteFrame,
  ): void {
    const sprite = this.images.sprite(asset.url);
    if (sprite === undefined) return;
    const screenX = x * STEP_SIZE - originX;
    const screenY = y * STEP_SIZE - originY;
    const frame = selectedFrame ?? spriteFrameForPhase(facing, 0);
    this.context.save();
    if (frame.mirrored) {
      this.context.translate(screenX + STEP_SIZE, 0);
      this.context.scale(-1, 1);
      this.context.drawImage(sprite, 0, frame.y, 16, 16, 0, screenY, 16, 16);
    } else {
      this.context.drawImage(sprite, 0, frame.y, 16, 16, screenX, screenY, 16, 16);
    }
    this.context.restore();
  }

  private scheduleAnimation(): void {
    if (this.animationFrame !== null) return;
    this.animationFrame = requestAnimationFrame((time) => {
      this.animationFrame = null;
      const snapshot = this.snapshot;
      const motion = this.playerMotion;
      if (snapshot === null || motion === null) return;
      this.draw(snapshot, time);
      if (time - motion.startedAt < MOVE_DURATION_MS) {
        this.scheduleAnimation();
      } else {
        this.playerMotion = null;
      }
    });
  }

  private stopAnimation(): void {
    this.playerMotion = null;
    if (this.animationFrame === null) return;
    cancelAnimationFrame(this.animationFrame);
    this.animationFrame = null;
  }

  private resourcesKey(resources: RetroMapResources): string {
    return [
      resources.map_id,
      resources.tileset_asset.url,
      resources.player_asset.url,
      ...Object.entries(resources.sprite_assets)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, asset]) => `${name}:${asset.url}`),
    ].join("|");
  }
}
