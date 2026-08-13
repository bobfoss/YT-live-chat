'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'yt_live_chat', 'browser.js'),
  'utf8',
);

function registeredPlugin() {
  let plugin = null;
  const context = {
    window: {
      YTLibraryBrowserPlugins: {
        apiVersion: 2,
        features: { entityCards: 1 },
        register(value) {
          plugin = value;
        },
      },
    },
  };
  vm.runInNewContext(source, context, { filename: 'browser.js' });
  return plugin;
}

test('browser asset registers recorded-chat card and detail extensions', () => {
  const plugin = registeredPlugin();
  assert.equal(plugin.id, 'live_chat');
  assert.deepEqual([...plugin.entityCards.kinds], ['video']);
  assert.equal(
    plugin.entityCards.capability,
    'video_live_chat_availability',
  );
  assert.equal(plugin.videoDetail.capability, 'video_live_chat_messages');
  assert.match(source, /host\.libraryChannels\(channelIds\)/);
  assert.match(source, /\^@\[\^\\s\/@\]\+\$\/u\.test\(authorName\)/);
  assert.match(source, /host\.ui\.localChannelHref\(authorReference\)/);
  assert.match(source, /document\.createElement\(linked \? 'a' : 'strong'\)/);
});

test('entity-card preparation retains only captured chat state', async () => {
  const plugin = registeredPlugin();
  const calls = [];
  const prepared = await plugin.entityCards.prepare(
    [
      { id: 'abcdefghijk' },
      { id: 'abcdefghijk' },
      { id: 'lmnopqrstuv' },
    ],
    {
      async requestJson(pathname, params) {
        calls.push({ pathname, params });
        return {
          videos: {
            abcdefghijk: { replay_status: 'captured', message_count: 2 },
            lmnopqrstuv: { replay_status: 'not_available' },
          },
        };
      },
    },
  );

  assert.equal(calls.length, 1);
  assert.deepEqual(
    Array.from(calls[0].params.id),
    ['abcdefghijk', 'lmnopqrstuv'],
  );
  assert.equal(prepared.size, 1);
  assert.equal(prepared.get('abcdefghijk').message_count, 2);
});

test('video detail omits the panel when chat is not captured', async () => {
  const plugin = registeredPlugin();
  const panel = await plugin.videoDetail.render('abcdefghijk', {
    supports: capability => capability === 'video_live_chat_messages',
    requestJson: async () => ({
      videos: { abcdefghijk: { replay_status: 'unobserved' } },
    }),
  });
  assert.equal(panel, null);
});
