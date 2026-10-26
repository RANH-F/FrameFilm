const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/ark-device.js'), 'utf8');
function frame(channel, data) {
    const b = new Uint8Array(data.length + 4);
    b.set([0x55, channel, data.length]); b.set(data, 3);
    b[b.length - 1] = b.slice(0, -1).reduce((a, x) => a + x, 0) & 255;
    return b;
}
function create(flags = 15, status = 0) {
    const window = { dispatchEvent() {}, CustomEvent: class {} };
    const context = vm.createContext({ window, Uint8Array, TextEncoder, AbortController, Promise, Error, Number, setTimeout, clearTimeout });
    vm.runInContext(source, context);
    const writes = [];
    window.ArkDevice.bind({
        connected: () => true,
        write: async b => {
            writes.push(b.slice());
            const data = b[1] === 0x59 ? [1, 0, 0, 0, flags] : [0, status];
            queueMicrotask(() => window.ArkDevice.notification(frame(b[1], data)));
        }
    });
    return { api: window.ArkDevice, writes };
}
test('atomic image open sends name once and never queues legacy switching or file IDs', async () => {
    const { api, writes } = create();
    const result = await api.openImage('测试.film');
    assert.equal(result.submitted, true);
    assert.deepEqual(writes.map(b => b[1]), [0x59, 0x4B]);
    assert.deepEqual(Array.from(writes[1].slice(3, -1)), [0, ...new TextEncoder().encode('测试.film'), 0]);
    assert.equal(api.busy(), false);
});
test('older firmware is reported before any display request', async () => {
    const { api, writes } = create(7);
    await assert.rejects(api.openImage('photo.film'), /升级/);
    assert.deepEqual(writes.map(b => b[1]), [0x59]);
});
test('missing file and busy responses do not silently retry or switch by legacy ID', async () => {
    for (const [status, pattern] of [[1, /参数/], [2, /未找到/], [3, /正在忙/]]) {
        const { api, writes } = create(15, status);
        await assert.rejects(api.openImage('photo.film'), pattern);
        assert.deepEqual(writes.map(b => b[1]), [0x59, 0x4B]);
        assert.equal(api.busy(), false);
    }
});
test('invalid basename and UTF-8 byte overflow are rejected before radio writes', async () => {
    const { api, writes } = create();
    for (const name of ['', '.', '..', 'a/b.film', 'a\\b.film', 'a\0b.film', '图'.repeat(64)]) {
        await assert.rejects(api.openImage(name), /文件名/);
    }
    assert.equal(writes.length, 0);
});
