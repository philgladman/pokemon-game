export type Direction = "north" | "south" | "west" | "east";

export interface Position {
  x: number;
  y: number;
}

export interface SourceAsset {
  kind: "tileset" | "sprite";
  name: string;
  url: string;
}

export interface TextInteraction {
  reference: string;
  status: "direct" | "unsupported";
  template_pages: string[];
  reason: string | null;
}

export interface ActorState {
  id: string;
  position: Position;
  facing: Direction;
  visible: boolean;
  sprite: string;
}

export interface RetroMapResources {
  map_id: string;
  tileset: string;
  tileset_asset: SourceAsset;
  tile_size: number;
  tiles_per_row: number;
  tile_ids: number[][];
  block_ids: number[][];
  player_asset: SourceAsset;
  sprite_assets: Record<string, SourceAsset>;
}

export interface ThreeDMapResources {
  map_id: string;
  tile_appearances: string[][];
  player_appearance: string;
  npc_appearances: Record<string, string>;
}

export interface MapDefinition {
  id: string;
  source_name: string;
  kind: "outdoor" | "indoor";
  last_map_target: string | null;
  width: number;
  height: number;
  walkable: boolean[][];
  actors: ActorState[];
}

export interface PlayerState {
  position: Position;
  facing: Direction;
  sprite: string;
}

export interface DialogState {
  interaction_id: string;
  pages: string[];
  page_index: number;
}

export type ControlMode =
  | "free"
  | "dialog"
  | "choice"
  | "scripted_movement"
  | "transition"
  | "battle"
  | "phase_boundary";

export interface ChoiceState {
  id: string;
  instance_id: string;
  prompt: string;
  options: { id: string; label: string }[];
  selected_index: number;
  cancel_index: number;
}

export interface MovementTrack {
  actor_id: string;
  start: Position;
  steps: Direction[];
}

export interface MovementCue {
  id: string;
  tracks: MovementTrack[];
}

export interface TransitionState {
  id: string;
}

export interface PartyMember {
  species_id: number;
  name: string;
  level: number;
}

export interface BattleMoveView {
  slot: number;
  name: string;
  pp: number;
  max_pp: number;
}

export interface BattlePokemonView {
  species: string;
  name: string;
  level: number;
  hp: number;
  max_hp: number;
  stats: PokemonStats;
  experience: number;
  stat_experience: PokemonStats;
  image_url: string;
  moves: BattleMoveView[];
}

export interface PokemonStats {
  hp: number;
  attack: number;
  defense: number;
  speed: number;
  special: number;
}

export interface BattleFrame {
  text: string;
  player_hp: number;
  rival_hp: number;
  player_pp: number[];
  player_level: number;
  player_max_hp: number;
  player_stats: PokemonStats;
  rival_level: number;
  rival_max_hp: number;
  rival_stats: PokemonStats;
  show_stats?: boolean;
}

export interface BattleBatch {
  id: string;
  frames: BattleFrame[];
}

export interface BattleSnapshot {
  id: string;
  turn: number;
  outcome: "ongoing" | "player_win" | "player_loss";
  player: BattlePokemonView;
  rival: BattlePokemonView;
  action_token: string | null;
  batch: BattleBatch | null;
}

export interface SessionSnapshot {
  map: MapDefinition;
  player: PlayerState;
  dialog: DialogState | null;
  choice: ChoiceState | null;
  control_mode: ControlMode;
  movement_cue: MovementCue | null;
  transition: TransitionState | null;
  flags: string[];
  has_starter: boolean;
  player_starter: string | null;
  rival_starter: string | null;
  party: PartyMember[];
  money: number;
  battle: BattleSnapshot | null;
}

export interface StateMessage {
  type: "state";
  request_id: string | null;
  state_version: number;
  action: string;
  reason: string | null;
  state: SessionSnapshot;
}

export interface PresentationContext {
  resetGait: boolean;
}

export interface ErrorMessage {
  type: "error";
  request_id: string | null;
  code: string;
  message: string;
}

export interface GameRenderer {
  update(snapshot: SessionSnapshot, presentation: PresentationContext): Promise<void>;
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

export type ServerMessage = StateMessage | ErrorMessage;
export type ClientMessage =
  | { type: "battle_action"; request_id: string; battle_id: string; action_token: string; slot: number | null }
  | { type: "acknowledge_battle"; request_id: string; battle_id: string; batch_id: string }
  | { type: "move"; request_id: string; direction: Direction; continued: boolean }
  | { type: "interact"; request_id: string }
  | {
      type: "choice";
      request_id: string;
      choice_id: string;
      intent: "previous" | "next" | "confirm" | "cancel";
    }
  | { type: "acknowledge_cue"; request_id: string; cue_id: string }
  | {
      type: "acknowledge_transition";
      request_id: string;
      transition_id: string;
    };
