// Kiểm tra ĐỒNG BỘ của còi cảnh báo (WP3) với drowsy_status.
// Nạp chính static/js/camera.js (stub DOM + AudioContext) rồi mô phỏng
// các trạng thái AI, xác nhận còi bật/tắt đúng nhịp.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../static/js/camera.js", import.meta.url), "utf8");

let beeps = 0;
let cleared = 0;
let intervalFn = null;

function fakeEl() {
    return {
        textContent: "", className: "",
        classList: { add() {}, remove() {} },
        querySelector() { return { textContent: "" }; },
        appendChild() {}, replaceChildren() {},
    };
}

class FakeAudioContext {
    constructor() { this.state = "running"; this.currentTime = 0; this.destination = {}; }
    resume() {}
    createOscillator() {
        return { type: "", frequency: {}, connect() {}, start() { beeps++; }, stop() {} };
    }
    createGain() { return { gain: {}, connect() {} }; }
}

const sandbox = {
    document: { querySelector: fakeEl, getElementById: fakeEl, createElement: fakeEl },
    window: {},
    AudioContext: FakeAudioContext,
    setInterval: (fn) => { intervalFn = fn; return 123; },
    clearInterval: () => { cleared++; },
    setTimeout: () => 0, clearTimeout: () => {},
    fetch: () => Promise.resolve({ json: () => ({}) }),
    console, Date,
};
sandbox.window.AudioContext = FakeAudioContext;

// Driver test nối vào cuối để cùng scope với `let alarmTimer`.
const driver = `
;(function(){
  const out = [];
  const ai = (s)=>({eye_status:'EYES OPEN',mouth_status:'NORMAL',head_status:'NORMAL',drowsy_status:s,ear:0.1,mar:0.1});
  out.push('decideAlarm: DROWSY='+decideAlarm('DROWSY')+' TIRED='+decideAlarm('TIRED')+' NORMAL='+decideAlarm('NORMAL'));
  updateAIStatus(ai('DROWSY'));
  out.push('[DROWSY] coi_bat='+(alarmTimer!==null)+' beeps='+__beeps());
  __tick(); __tick();
  out.push('[2 nhip] beeps='+__beeps());
  updateAIStatus(ai('TIRED'));
  out.push('[TIRED] coi_bat='+(alarmTimer!==null));
  updateAIStatus(ai('NORMAL'));
  out.push('[NORMAL] coi_bat='+(alarmTimer!==null)+' clearInterval_goi='+__cleared());
  updateAIStatus(ai('DROWSY'));
  out.push('[DROWSY lai] coi_bat='+(alarmTimer!==null));
  globalThis.__RESULT__ = out;
})();
`;

sandbox.__beeps = () => beeps;
sandbox.__cleared = () => cleared;
sandbox.__tick = () => { if (intervalFn) intervalFn(); };
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
vm.runInContext(src + driver, sandbox);

const out = sandbox.__RESULT__;
out.forEach((l) => console.log(l));

// Khẳng định đồng bộ:
const ok =
    out[0] === "decideAlarm: DROWSY=true TIRED=false NORMAL=false" &&
    out[1] === "[DROWSY] coi_bat=true beeps=1" &&
    out[2] === "[2 nhip] beeps=3" &&
    out[3] === "[TIRED] coi_bat=false" &&
    out[4].startsWith("[NORMAL] coi_bat=false") &&
    out[5] === "[DROWSY lai] coi_bat=true";

console.log(ok ? "\nKET QUA: PASS - coi dong bo voi drowsy_status" : "\nKET QUA: FAIL");
process.exit(ok ? 0 : 1);
