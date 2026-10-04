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

function registeredPlugin(globals = {}) {
  let plugin = null;
  const context = {
    ...globals,
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

class TestElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.className = '';
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.value = '';
  }

  set textContent(value) {
    this.value = String(value);
    this.children = [];
  }

  get textContent() {
    return this.value + this.children.map(child => child.textContent).join('');
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.value = ''; this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}

function descendants(element, className) {
  return [element, ...element.children.flatMap(child => descendants(child, className))]
    .filter(child => child.className.split(' ').includes(className));
}

function renderChat(item) {
  const plugin = registeredPlugin({ document: { createElement: name => new TestElement(name) } });
  return plugin.search.renderResult({ video_id: 'abcdefghijk', ...item }, {
    ui: {
      localVideoHref: id => `/videos/${id}`,
      localChannelHref: id => `/channels/${id}`,
      formatTime: value => value || '',
    },
  });
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
  assert.equal(plugin.search.serverResults, true);
  assert.equal(plugin.channelVideoTabs[0].label, 'Chat history');
  assert.equal(
    plugin.channelVideoTabs[0].capability,
    'channel_live_chat_history',
  );
  assert.match(source, /host\.libraryChannels\(channelIds\)/);
  assert.match(source, /\^@\[\^\\s\/@\]\+\$\/u\.test\(authorName\)/);
  assert.match(source, /host\.ui\.localChannelHref\(authorReference\)/);
  assert.match(source, /document\.createElement\(linked \? 'a' : 'strong'\)/);
  assert.match(source, /MESSAGE_SCROLL_THRESHOLD/);
  assert.match(source, /dataset\.ytlcScroll/);
  assert.match(source, /dataset\.ytlcSearchInput/);
  assert.match(source, /messages\$\{searchQuery \? '\/search' : ''\}/);
  assert.doesNotMatch(source, /data\.ytlcMore/);
  assert.match(styles, /a\.ytlc-message-author \{ color: var\(--accent\);/);
  assert.match(styles, /\.ytlc-message-scroll \{[^}]*overflow: auto/);
  assert.match(styles, /\.ytlc-message-search/);
  assert.doesNotMatch(styles, /\.ytlc-load-more/);
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

test('collection fetch preserves blank query and delegates shared sort and page', async () => {
  const plugin = registeredPlugin();
  const calls = [];
  const payload = {total: 12, totalIsExact: true, limit: 5, offset: 5, results: []};
  const host = {requestJson: async (...args) => { calls.push(args); return payload; }};
  assert.equal(await plugin.collection.fetch({query: '', limit: 5, offset: 5, sort: 'oldest'}, host), payload);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ['collection', {q: '', limit: 5, offset: 5, sort: 'oldest', own: '1', others: '1'}],
  ]);
  assert.deepEqual([...plugin.collection.sorts], ['newest', 'oldest']);
  assert.equal(plugin.search.fetch, undefined);
  assert.equal(plugin.search.searchField.key, 'live_chat');
  assert.deepEqual([...plugin.search.searchField.appliesToKinds], ['videos']);
  assert.equal(plugin.search.videoFacet.presentHashParam, 'with-live-chats');
  assert.equal(plugin.search.videoFacet.absentDisabledPreferenceKey, 'plugins.live_chat.filters.hide_absent');
  assert.equal(plugin.search.catalogCount({pluginStatus: {searchCatalogCount: 12}}), 12);
  await plugin.collection.fetch({query: 'hi', limit: 5, offset: 0, sort: 'newest', filters: {others: false}}, host);
  assert.equal(calls.at(-1)[1].own, '1');
  assert.equal(calls.at(-1)[1].others, '0');
  assert.deepEqual(Array.from(plugin.search.filters, option => option.key), ['own', 'others']);
});

test('search preparation batches only selected video cards and captured authors', async () => {
  const plugin = registeredPlugin();
  const calls = [];
  const items = [{video_id: 'abcdefghijk', messages: [{authorChannelId: 'UCauthor'}]},
    {video_id: 'lmnopqrstuv', messages: [{authorChannelId: 'UCauthor'}]}];
  await plugin.search.prepareResults(items, {
    libraryVideos: async ids => { calls.push([...ids]); return new Map([['abcdefghijk', {
      title: 'Canonical title', metadata_channel_thumbnail_path: 'thumbs/creator.jpg',
      metadata_channel_name: 'Creator',
    }]]); },
    libraryChannels: async ids => { calls.push([...ids]); return new Map([['UCauthor', {}]]); },
  });
  assert.deepEqual(calls, [['abcdefghijk', 'lmnopqrstuv'], ['UCauthor']]);
  assert.equal(items[0].title, 'Canonical title');
  assert.equal(items[0].channelThumbnailPath, 'thumbs/creator.jpg');
  assert.equal(items[0].channelName, 'Creator');
  assert.equal(items[1].channelThumbnailPath, '');
  assert.equal(items[1].channelName, '');
  assert.ok(items[0].authorChannels.has('UCauthor'));
});

test('chat cards use cached author and uploader thumbnails without changing links', () => {
  const card = renderChat({
    title: 'Captured video', channelName: 'Creator', channelThumbnailPath: '/thumbs/creator.jpg',
    authorChannels: new Map([['UCauthor', {thumbnail_path: 'thumbs/author.jpg'}]]),
    messages: [{authorChannelId: 'UCauthor', authorName: '@Known', offsetMs: 125000,
      messageText: 'Hello from chat'}],
  });
  const [avatar] = descendants(card, 'ytlc-message').flatMap(row => descendants(row, 'ytlc-avatar'));
  assert.equal(avatar.attributes['aria-hidden'], 'true');
  assert.equal(avatar.children[0].tagName, 'img');
  assert.equal(avatar.children[0].src, '/thumbs/author.jpg');
  assert.equal(avatar.children[0].alt, '');
  assert.equal(avatar.children[0].loading, 'lazy');
  assert.equal(avatar.children[0].decoding, 'async');
  const author = descendants(card, 'ytlc-message-author')[0];
  assert.equal(author.tagName, 'a');
  assert.equal(author.textContent, '@Known');
  assert.equal(author.href, '/channels/@Known');
  assert.equal(descendants(card, 'ytlc-message-time')[0].href,
    'https://www.youtube.com/watch?v=abcdefghijk&t=125s');
  assert.equal(descendants(card, 'ytlc-message-text')[0].textContent, 'Hello from chat');
  const title = descendants(card, 'video-title')[0];
  assert.equal(title.href, '/videos/abcdefghijk');
  assert.equal(descendants(title, 'creator-name')[0].textContent, 'Captured video');
  assert.equal(descendants(title, 'ytlc-title-avatar')[0].children[0].src, '/thumbs/creator.jpg');
});

test('unknown, missing-image and unnamed authors get initial placeholders', () => {
  const card = renderChat({
    authorChannels: new Map([['UCknown', {}]]),
    messages: [
      {authorChannelId: 'UCunknown', authorName: '@unknown'},
      {authorChannelId: 'UCknown', authorName: '@Known'},
      {authorName: ''},
      {authorName: '@😀friend'},
    ],
  });
  const rows = descendants(card, 'ytlc-message');
  assert.deepEqual(rows.map(row => descendants(row, 'ytlc-avatar')[0].textContent), ['U', 'K', '?', '😀']);
  assert.ok(rows.every(row => descendants(row, 'ytlc-avatar')[0].children.length === 0));
  assert.deepEqual(rows.map(row => descendants(row, 'ytlc-message-author')[0].tagName),
    ['strong', 'a', 'strong', 'strong']);
  assert.equal(descendants(card, 'ytlc-title-avatar')[0].textContent, '?');
});

test('broken cached images fall back and remote thumbnail URLs are not loaded', () => {
  const card = renderChat({
    channelName: 'Uploader', channelThumbnailPath: 'thumbs/missing.jpg',
    authorChannels: new Map([
      ['UCbroken', {thumbnail_path: 'thumbs/missing.jpg'}],
      ['UCremote', {thumbnail_path: 'https://example.org/avatar.jpg'}],
      ['UCrelative', {thumbnail_path: '//example.org/avatar.jpg'}],
      ['UCwindows', {thumbnail_path: '\\\\example.org\\avatar.jpg'}],
      ['UCpadded', {thumbnail_path: ' https://example.org/avatar.jpg '}],
    ]),
    messages: [
      {authorChannelId: 'UCbroken', authorName: '@Broken'},
      {authorChannelId: 'UCremote', authorName: '@Remote'},
      {authorChannelId: 'UCrelative', authorName: '@Relative'},
      {authorChannelId: 'UCwindows', authorName: '@Windows'},
      {authorChannelId: 'UCpadded', authorName: '@Padded'},
    ],
  });
  const avatars = descendants(card, 'ytlc-avatar');
  assert.equal(avatars[0].children.length, 1);
  assert.equal(avatars[1].children.length, 1);
  avatars[0].children[0].listeners.error();
  avatars[1].children[0].listeners.error();
  assert.deepEqual(avatars.map(avatar => avatar.textContent), ['U', 'B', 'R', 'R', 'W', 'P']);
  assert.ok(avatars.every(avatar => avatar.children.length === 0));
});
