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
const styles = fs.readFileSync(
  path.join(__dirname, '..', 'yt_live_chat', 'browser.css'),
  'utf8',
);

function registeredPlugin() {
  let plugin = null;
  const context = {
    window: {
      YTLibraryBrowserPlugins: {
        apiVersion: 2,
        features: { channelVideoTabs: 1, entityCards: 1 },
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
  assert.equal(plugin.channelVideoTabs[0].label, 'Chat history');
  assert.equal(
    plugin.channelVideoTabs[0].capability,
    'channel_live_chat_history',
  );
  assert.match(source, /host\.libraryChannels\(channelIds\)/);
  assert.match(source, /\^@\[\^\\s\/@\]\+\$\/u\.test\(authorName\)/);
  assert.match(source, /host\.ui\.localChannelHref\(authorReference\)/);
  assert.match(source, /document\.createElement\(linked \? 'a' : 'strong'\)/);
  assert.match(styles, /a\.ytlc-message-author \{ color: var\(--accent\);/);
});

test('channel chat-history tab counts and loads participated video ids', async () => {
  const plugin = registeredPlugin();
  const tab = plugin.channelVideoTabs[0];
  const calls = [];
  const host = {
    async requestJson(pathname, params) {
      calls.push({ pathname, params });
      return {
        videos: [{ videoId: 'abcdefghijk' }, { videoId: 'lmnopqrstuv' }],
        total: 2,
        limit: params.limit,
        offset: params.offset,
      };
    },
  };
  const channel = { channel_id: 'UCauthor1' };

  assert.equal(await tab.count(channel, host), 2);
  const page = await tab.load(channel, host, { limit: 50, offset: 0 });

  assert.deepEqual(Array.from(page.videoIds), ['abcdefghijk', 'lmnopqrstuv']);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    {
      pathname: 'channels/UCauthor1/videos',
      params: { limit: 1, offset: 0 },
    },
    {
      pathname: 'channels/UCauthor1/videos',
      params: { limit: 50, offset: 0 },
    },
  ]);
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
