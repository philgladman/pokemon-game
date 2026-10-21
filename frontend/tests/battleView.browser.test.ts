import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { createServer } from "vite";
import { expect, it } from "vitest";

const chrome = [
  process.env.CHROME_BIN,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/usr/bin/google-chrome",
].find((candidate): candidate is string => candidate !== undefined && existsSync(candidate));

const page = `<!doctype html><html><head><meta charset="UTF-8"></head><body><section id="battle" class="battle"></section><button id="outside">Outside</button>
<script type="module">
import { BattleView } from '/src/battleView.ts';
import '/src/style.css';
const assert = (condition, description) => { if (!condition) throw new Error(description); };
try {
  const root = document.getElementById('battle');
  const view = new BattleView(root);
  const stats = {hp: 20, attack: 12, defense: 11, speed: 10, special: 13};
  const pokemon = {name: 'BULBASAUR', level: 5, hp: 20, max_hp: 20,
    species: 'BULBASAUR', stats, experience: 135,
    stat_experience: {hp: 0, attack: 0, defense: 0, speed: 0, special: 0},
    image_url: 'data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA=',
    moves: [{slot: 0, name: 'TACKLE', pp: 10, max_pp: 35}]};
  const battle = {id: 'battle', turn: 0, outcome: 'ongoing', player: pokemon,
    rival: pokemon, action_token: null, batch: {id: 'intro', frames: []}};
  let display = {battle, frame: null, text: 'Challenge!', ready: true,
    selected: 0, error: null, disconnected: false};
  const focused = () => document.activeElement?.dataset.command;
  view.render(display);
  root.querySelector('button').focus();
  assert(focused() === 'continue', 'initial Continue focus');
  view.render({...display, ready: false});
  assert(document.activeElement === root, 'pending text keeps focus in battle');
  view.render({...display, text: 'Send out!'});
  assert(focused() === 'continue', 'next frame restores Continue focus');
  display = {...display, battle: {...battle, batch: null, action_token: 'turn-1'}};
  view.render(display);
  assert(focused() === 'move-0', 'intro completion moves focus to move menu');
  view.render({...display, ready: false});
  assert(document.activeElement === root, 'pending move keeps focus in battle');
  display = {...display, battle: {...battle, batch: {id: 'turn', frames: []}}};
  view.render({...display, ready: false});
  view.render(display);
  assert(focused() === 'continue', 'move response moves focus to Continue');
  view.render({...display, ready: false});
  document.getElementById('outside').focus();
  view.render(display);
  assert(document.activeElement.id === 'outside', 'async updates do not steal focus after Tab away');
  const widths = [];
  for (const hp of [0, 8, 20]) {
    view.render({...display, battle: {...battle, player: {...pokemon, hp}}});
    const meter = root.querySelector('.battle-player [role="meter"]');
    const fill = meter.querySelector('.battle-hp-fill');
    assert(meter.getAttribute('aria-valuenow') === String(hp), 'accessible HP matches snapshot');
    assert(meter.getAttribute('aria-valuemax') === '20', 'accessible maximum matches snapshot');
    assert(getComputedStyle(fill).backgroundColor !== getComputedStyle(meter).backgroundColor,
      'HP fill contrasts with empty track');
    widths.push(fill.getBoundingClientRect().width);
  }
  assert(widths[0] === 0 && widths[1] > 0 && widths[2] > widths[1], 'empty, partial, full HP are distinct');
  assert(Math.abs(widths[1] / widths[2] - 0.4) < 0.01, '8/20 HP fills forty percent of the track');
  const finalStats = {...stats, hp: 23, attack: 15};
  const frame = {text: 'Enemy CHARMANDER fainted!', player_hp: 8, rival_hp: 0, player_pp: [9],
    player_level: 5, player_max_hp: 20, player_stats: stats,
    rival_level: 5, rival_max_hp: 20, rival_stats: stats};
  const completed = {...battle, outcome: 'player_win',
    player: {...pokemon, level: 6, hp: 11, max_hp: 23, stats: finalStats}};
  view.render({...display, battle: completed, frame, text: frame.text});
  assert(root.querySelector('.battle-player h2').textContent === 'BULBASAUR · Lv 5',
    'final snapshot level does not leak into faint frame');
  assert(root.querySelector('.battle-player p').textContent === 'HP 8 / 20',
    'final snapshot max HP does not leak into faint frame');
  assert(root.querySelector('.battle-player [role="meter"]').getAttribute('aria-valuemax') === '20',
    'accessible maximum uses faint frame');
  assert(root.querySelector('.battle-stats').hidden, 'stats panel stays hidden before level-up');
  view.render({...display, battle: completed, frame: {...frame,
    player_level: 6, player_max_hp: 23, player_hp: 11, player_stats: finalStats, show_stats: true},
    text: 'BULBASAUR grew to level 6!'});
  assert(root.querySelector('.battle-player h2').textContent === 'BULBASAUR · Lv 6', 'level-up frame updates level');
  assert(root.querySelector('.battle-player p').textContent === 'HP 11 / 23', 'level-up frame updates HP');
  assert(!root.querySelector('.battle-stats').hidden, 'level-up frame reveals stats');
  assert(root.querySelector('.battle-stats').textContent.includes('ATTACK 15'), 'level-up panel uses authoritative stats');
  view.render({...display, battle: {...completed, batch: null}});
  assert(!root.querySelector('[data-command="reload"]'), 'completed battle has no restart milestone');
  assert(root.querySelectorAll('button').length === 0, 'completed battle cannot submit another move');
  document.body.dataset.result = 'passed';
} catch (error) {
  document.body.dataset.result = 'failed';
  document.body.append(String(error));
}
</script></body></html>`;

it.skipIf(chrome === undefined)("preserves battle focus and scales HP bars in a real browser", async () => {
  const profile = await mkdtemp(join(tmpdir(), "pokemon-battle-focus-"));
  const server = await createServer({
    configFile: false,
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "battle-focus-regression",
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url !== "/__battle_focus_test") return next();
          response.setHeader("Content-Type", "text/html");
          response.end(page);
        });
      },
    }],
  });
  try {
    await server.listen();
    const address = server.httpServer?.address();
    if (address === null || address === undefined || typeof address === "string") throw new Error("Missing test server address");
    const { stdout } = await promisify(execFile)(chrome!, [
      "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
      `--user-data-dir=${profile}`, "--dump-dom", "--virtual-time-budget=2000",
      `http://127.0.0.1:${address.port}/__battle_focus_test`,
    ], { timeout: 15000, maxBuffer: 1024 * 1024 });
    expect(stdout).toContain('data-result="passed"');
  } finally {
    await server.close();
    await rm(profile, { recursive: true, force: true });
  }
}, 20000);
