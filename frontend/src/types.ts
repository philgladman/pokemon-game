export type Direction = "north" | "south" | "west" | "east";

export interface Position {
  x: number;
  y: number;
}

export interface PrimitiveAsset {
  type: "primitive";
  shape: "flat" | "tree" | "box" | "capsule";
  color: string;
  secondary_color: string | null;
  scale: [number, number, number];
}

export interface GltfAsset {
  type: "gltf";
  url: string;
  scale: [number, number, number];
  fallback: PrimitiveAsset;
}

export interface AppearanceDefinition {
  id: string;
  source: PrimitiveAsset | GltfAsset;
  base_color: string | null;
}

export interface TileDefinition {
  id: string;
  walkable: boolean;
  surfable: boolean;
  appearance: string;
}

export interface NPCDefinition {
  id: string;
  name: string;
  position: Position;
  facing: Direction;
  dialog: string[];
  appearance: string;
}

export interface MapDefinition {
  id: string;
  name: string;
  width: number;
  height: number;
  tiles: string[][];
  tile_definitions: Record<string, TileDefinition>;
  player_spawn: Position | null;
  npcs: NPCDefinition[];
}

export interface PlayerState {
  position: Position;
  facing: Direction;
  appearance: string;
}

export interface DialogState {
  npc_id: string;
  speaker: string;
  lines: string[];
  line_index: number;
}

export interface SessionSnapshot {
  map: MapDefinition;
  asset_manifest: Record<string, AppearanceDefinition>;
  player: PlayerState;
  dialog: DialogState | null;
}

export interface StateMessage {
  type: "state";
  request_id: string | null;
  state_version: number;
  action: string;
  reason: string | null;
  state: SessionSnapshot;
}

export interface ErrorMessage {
  type: "error";
  request_id: string | null;
  code: string;
  message: string;
}

export type ServerMessage = StateMessage | ErrorMessage;
export type ClientMessage =
  | { type: "move"; request_id: string; direction: Direction }
  | { type: "interact"; request_id: string };
