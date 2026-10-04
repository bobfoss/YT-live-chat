(() => {
  'use strict';

  const browserApi = window.YTLibraryBrowserPlugins;
  if (!browserApi || browserApi.apiVersion !== 2 || browserApi.features?.entityCards !== 1) {
    return;
  }

  const MESSAGE_PAGE_SIZE = 100;
  const MESSAGE_SCROLL_THRESHOLD = 220;

  function formatCount(value, singular, plural = `${singular}s`) {
    const count = Math.max(0, Number(value || 0));
    return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
  }

  function timestampLabel(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return hours
      ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      : `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  function watchUrl(videoId, offsetMs) {
    const seconds = Math.max(0, Math.floor(Number(offsetMs || 0) / 1000));
    return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}&t=${seconds}s`;
  }

  function availabilityElement(state) {
    const metadata = document.createElement('span');
    metadata.className = 'ytlc-availability';
    metadata.title = formatCount(state?.message_count, 'message');
    metadata.innerHTML = `
      <svg class="ytlc-availability-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 4h16v11H8l-4 4V4Zm3 4h10M7 11h7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>
      <span>Recorded chat</span>
    `;
    return metadata;
  }

  async function prepareEntityCards(entities, host) {
    const videoIds = [...new Set(entities.map(entity => String(entity.id || '')).filter(Boolean))];
    const captured = new Map();
    for (let start = 0; start < videoIds.length; start += 500) {
      const payload = await host.requestJson('videos', {
        id: videoIds.slice(start, start + 500),
      });
      for (const [videoId, state] of Object.entries(payload.videos || {})) {
        if (state?.replay_status === 'captured') captured.set(videoId, state);
      }
    }
    return captured;
  }

  function renderEntityCard(entity, captured) {
    const state = captured?.get(String(entity.id || ''));
    if (!state) return null;
    return { primaryMetadata: [availabilityElement(state)] };
  }

  async function resolveAuthorChannels(messages, host) {
    if (typeof host.libraryChannels !== 'function') return new Map();
    const channelIds = [...new Set(
      messages.map(message => String(message.authorChannelId || '')).filter(Boolean),
    )];
    if (!channelIds.length) return new Map();
    try {
      return await host.libraryChannels(channelIds);
    } catch (error) {
      console.error('YT Live Chat author lookup failed:', error);
      return new Map();
    }
  }

  function messageRow(videoId, message, authorChannels, host, highlight = false) {
    const row = document.createElement('div');
    row.className = 'ytlc-message';

    const timestamp = document.createElement('a');
    timestamp.className = 'ytlc-message-time';
    timestamp.href = watchUrl(videoId, message.offsetMs);
    timestamp.target = '_blank';
    timestamp.rel = 'noreferrer';
    timestamp.textContent = timestampLabel(message.offsetMs);
    timestamp.setAttribute(
      'aria-label',
      `Open video at ${timestamp.textContent} on YouTube`,
    );

    const body = document.createElement('div');
    body.className = 'ytlc-message-body';
    const authorChannelId = String(message.authorChannelId || '');
    const linked = authorChannelId
      && authorChannels.has(authorChannelId)
      && typeof host.ui?.localChannelHref === 'function';
    const author = document.createElement(linked ? 'a' : 'strong');
    author.className = 'ytlc-message-author';
    const authorName = String(message.authorName || 'Unknown author');
    author.textContent = authorName;
    if (linked) {
      const authorReference = /^@[^\s/@]+$/u.test(authorName)
        ? authorName
        : authorChannelId;
      author.href = host.ui.localChannelHref(authorReference);
      author.setAttribute('aria-label', `Open ${author.textContent} in YT Library`);
    }
    const text = document.createElement('span');
    text.className = 'ytlc-message-text';
    if (
      highlight
      && typeof host.ui?.searchHighlight?.snippetHtml === 'function'
    ) {
      text.innerHTML = host.ui.searchHighlight.snippetHtml(String(message.snippet || ''));
    } else {
      text.textContent = String(message.messageText || '');
    }
    body.append(author, text);
    row.append(timestamp, body);
    return row;
  }

  function setExpanded(panel, expanded) {
    const toggle = panel.querySelector('[data-ytlc-toggle]');
    const label = panel.querySelector('[data-ytlc-toggle-label]');
    const content = panel.querySelector('[data-ytlc-content]');
    if (toggle instanceof HTMLButtonElement) {
      toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }
    if (label instanceof HTMLElement) {
      label.textContent = expanded ? 'Hide chat' : 'Show chat';
    }
    if (content instanceof HTMLElement) content.hidden = !expanded;
  }

  function resetMessageView(panel) {
    const generation = Number(panel.dataset.ytlcLoadGeneration || 0) + 1;
    panel.dataset.ytlcLoadGeneration = String(generation);
    panel.dataset.ytlcLoading = 'false';
    panel.dataset.ytlcNextOffset = '0';
    panel.dataset.ytlcTotal = '';
    panel.querySelector('.ytlc-messages')?.replaceChildren();
    const status = panel.querySelector('.ytlc-message-status');
    if (status instanceof HTMLElement) status.textContent = '';
    const loading = panel.querySelector('[data-ytlc-loading]');
    if (loading instanceof HTMLElement) loading.hidden = true;
    const scroll = panel.querySelector('[data-ytlc-scroll]');
    if (scroll instanceof HTMLElement) scroll.scrollTop = 0;
  }

  function loadNextMessagePageIfNeeded(panel, host) {
    const scroll = panel.querySelector('[data-ytlc-scroll]');
    if (!(scroll instanceof HTMLElement)) return;
    if (panel.dataset.ytlcLoading === 'true') return;
    const nextOffset = Number(panel.dataset.ytlcNextOffset || 0);
    const total = Number(panel.dataset.ytlcTotal || 0);
    if (nextOffset >= total) return;
    const remaining = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight;
    if (remaining < MESSAGE_SCROLL_THRESHOLD) void loadMessagePage(panel, host);
  }

  async function loadMessagePage(panel, host) {
    const videoId = panel.dataset.ytlcVideo || '';
    const messages = panel.querySelector('.ytlc-messages');
    const status = panel.querySelector('.ytlc-message-status');
    const loading = panel.querySelector('[data-ytlc-loading]');
    if (!videoId || !(messages instanceof HTMLElement)) return;
    if (panel.dataset.ytlcLoading === 'true') return;
    const offset = Number(panel.dataset.ytlcNextOffset || 0);
    const knownTotal = panel.dataset.ytlcTotal;
    if (knownTotal !== '' && offset >= Number(knownTotal || 0)) return;
    const generation = Number(panel.dataset.ytlcLoadGeneration || 0);
    const searchQuery = String(panel.dataset.ytlcQuery || '').trim();
    panel.dataset.ytlcLoading = 'true';
    if (loading instanceof HTMLElement) loading.hidden = false;
    if (offset === 0 && status instanceof HTMLElement) {
      status.textContent = searchQuery
        ? 'Searching recorded chat...'
        : 'Loading recorded chat...';
    }
    try {
      const payload = await host.requestJson(
        `videos/${encodeURIComponent(videoId)}/messages${searchQuery ? '/search' : ''}`,
        searchQuery
          ? { limit: MESSAGE_PAGE_SIZE, offset, q: searchQuery }
          : { limit: MESSAGE_PAGE_SIZE, offset },
      );
      if (generation !== Number(panel.dataset.ytlcLoadGeneration || 0)) return;
      const pageMessages = searchQuery ? (payload.matches || []) : (payload.messages || []);
      const authorChannels = await resolveAuthorChannels(pageMessages, host);
      if (generation !== Number(panel.dataset.ytlcLoadGeneration || 0)) return;
      if (offset === 0) messages.replaceChildren();
      messages.append(...pageMessages.map(
        message => messageRow(videoId, message, authorChannels, host, Boolean(searchQuery)),
      ));
      const loaded = Number(payload.offset || 0) + pageMessages.length;
      const total = Number(payload.total || loaded);
      panel.dataset.ytlcNextOffset = String(loaded);
      panel.dataset.ytlcTotal = String(total);
      if (status instanceof HTMLElement) {
        if (searchQuery && total === 0) {
          status.textContent = `No matches for “${searchQuery}”`;
        } else if (total === 0) {
          status.textContent = 'This capture contains no user messages.';
        } else {
          const unit = searchQuery ? (total === 1 ? 'match' : 'matches') : 'messages';
          status.textContent = `${loaded.toLocaleString()} of ${total.toLocaleString()} ${unit}`;
        }
      }
      requestAnimationFrame(() => loadNextMessagePageIfNeeded(panel, host));
    } catch (error) {
      if (generation !== Number(panel.dataset.ytlcLoadGeneration || 0)) return;
      if (status instanceof HTMLElement) {
        status.textContent = error instanceof Error ? error.message : String(error);
      }
    } finally {
      if (generation === Number(panel.dataset.ytlcLoadGeneration || 0)) {
        panel.dataset.ytlcLoading = 'false';
        if (loading instanceof HTMLElement) loading.hidden = true;
      }
    }
  }

  async function renderVideoPanel(videoId, host) {
    if (!host.supports('video_live_chat_messages')) return null;
    const payload = await host.requestJson('videos', { id: [videoId] });
    const state = payload.videos?.[videoId];
    if (state?.replay_status !== 'captured') return null;

    const panel = document.createElement('article');
    panel.className = 'card ytlc-panel';
    panel.dataset.ytlcVideo = videoId;
    const contentId = `ytlc-content-${videoId.replace(/[^A-Za-z0-9_-]/g, '-')}`;

    const heading = document.createElement('div');
    heading.className = 'ytlc-panel-heading';
    const titleGroup = document.createElement('div');
    const kind = document.createElement('div');
    kind.className = 'result-kind';
    kind.textContent = 'YT Live Chat';
    const title = document.createElement('h3');
    title.textContent = 'Recorded chat';
    const summary = document.createElement('div');
    summary.className = 'ytlc-panel-summary';
    summary.textContent = [
      formatCount(state.message_count, 'message'),
      formatCount(state.author_count, 'author'),
    ].join(' · ');
    titleGroup.append(kind, title, summary);

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'ytlc-chat-toggle';
    toggle.dataset.ytlcToggle = '';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', contentId);
    const toggleLabel = document.createElement('span');
    toggleLabel.dataset.ytlcToggleLabel = '';
    toggleLabel.textContent = 'Show chat';
    const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chevron.classList.add('ytlc-toggle-chevron');
    chevron.setAttribute('viewBox', '0 0 24 24');
    chevron.setAttribute('aria-hidden', 'true');
    chevron.innerHTML = '<path d="M9 18l6-6-6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>';
    toggle.append(toggleLabel, chevron);
    heading.append(titleGroup, toggle);

    const content = document.createElement('div');
    content.id = contentId;
    content.dataset.ytlcContent = '';
    content.hidden = true;
    const search = document.createElement('form');
    search.className = 'ytlc-message-search';
    search.dataset.ytlcSearch = '';
    search.setAttribute('role', 'search');
    const searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.dataset.ytlcSearchInput = '';
    searchInput.setAttribute('aria-label', 'Search recorded chat');
    searchInput.placeholder = 'Search recorded chat';
    searchInput.autocomplete = 'off';
    const searchButton = document.createElement('button');
    searchButton.type = 'submit';
    searchButton.textContent = 'Search';
    const clearSearch = document.createElement('button');
    clearSearch.type = 'button';
    clearSearch.dataset.ytlcSearchClear = '';
    clearSearch.textContent = 'Clear';
    clearSearch.hidden = true;
    search.append(searchInput, searchButton, clearSearch);
    const status = document.createElement('div');
    status.className = 'ytlc-message-status';
    status.setAttribute('aria-live', 'polite');
    const scroll = document.createElement('div');
    scroll.className = 'ytlc-message-scroll';
    scroll.dataset.ytlcScroll = '';
    scroll.setAttribute('role', 'region');
    scroll.setAttribute('aria-label', 'Recorded chat messages');
    scroll.tabIndex = 0;
    const messages = document.createElement('div');
    messages.className = 'ytlc-messages';
    const loading = document.createElement('div');
    loading.className = 'ytlc-message-loading';
    loading.dataset.ytlcLoading = '';
    loading.textContent = 'Loading…';
    loading.hidden = true;
    scroll.append(messages, loading);
    content.append(search, status, scroll);
    panel.append(heading, content);

    scroll.addEventListener('scroll', () => {
      loadNextMessagePageIfNeeded(panel, host);
    });

    panel.addEventListener('submit', event => {
      const form = event.target.closest('[data-ytlc-search]');
      if (!(form instanceof HTMLFormElement)) return;
      event.preventDefault();
      const input = form.querySelector('[data-ytlc-search-input]');
      const query = input instanceof HTMLInputElement ? input.value.trim() : '';
      if (input instanceof HTMLInputElement) input.value = query;
      panel.dataset.ytlcQuery = query;
      const clear = form.querySelector('[data-ytlc-search-clear]');
      if (clear instanceof HTMLButtonElement) clear.hidden = !query;
      resetMessageView(panel);
      void loadMessagePage(panel, host);
    });

    panel.addEventListener('input', event => {
      const input = event.target.closest('[data-ytlc-search-input]');
      if (!(input instanceof HTMLInputElement)) return;
      const clear = panel.querySelector('[data-ytlc-search-clear]');
      if (clear instanceof HTMLButtonElement) clear.hidden = !input.value;
      if (!input.value && panel.dataset.ytlcQuery) {
        panel.dataset.ytlcQuery = '';
        resetMessageView(panel);
        void loadMessagePage(panel, host);
      }
    });

    panel.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const clear = target.closest('[data-ytlc-search-clear]');
      if (clear instanceof HTMLButtonElement) {
        const input = panel.querySelector('[data-ytlc-search-input]');
        if (input instanceof HTMLInputElement) input.value = '';
        clear.hidden = true;
        panel.dataset.ytlcQuery = '';
        resetMessageView(panel);
        void loadMessagePage(panel, host);
        return;
      }
      const toggleButton = target.closest('[data-ytlc-toggle]');
      if (toggleButton instanceof HTMLButtonElement) {
        const expanded = toggleButton.getAttribute('aria-expanded') === 'true';
        setExpanded(panel, !expanded);
        if (!expanded && !panel.querySelector('.ytlc-message')) {
          resetMessageView(panel);
          void loadMessagePage(panel, host);
        }
        return;
      }
    });
    return panel;
  }

  async function channelChatHistory(channel, host, { limit, offset }) {
    const channelId = String(channel?.channel_id || '');
    const payload = await host.requestJson(
      `channels/${encodeURIComponent(channelId)}/videos`,
      { limit, offset },
    );
    return {
      videoIds: (payload.videos || [])
        .map(video => String(video.videoId || ''))
        .filter(Boolean),
      total: Number(payload.total || 0),
      limit: Number(payload.limit || limit),
      offset: Number(payload.offset || offset),
    };
  }

  const channelVideoTabs = browserApi.features?.channelVideoTabs === 1
    ? [{
      id: 'chat-history',
      label: 'Chat history',
      capability: 'channel_live_chat_history',
      emptyMessage: 'No recorded chat participation found for this channel.',
      count: async (channel, host) => {
        const payload = await channelChatHistory(
          channel,
          host,
          { limit: 1, offset: 0 },
        );
        return payload.total;
      },
      load: channelChatHistory,
    }]
    : [];

  async function prepareSearchResults(items, host) {
    const [videos, authors] = await Promise.all([
      host.libraryVideos([...new Set(items.map(item => item.video_id))]),
      resolveAuthorChannels(items.flatMap(item => item.messages || []), host),
    ]);
    for (const item of items) {
      item.title = videos.get(item.video_id)?.title || item.title || '';
      item.authorChannels = authors;
    }
  }

  function chatCard(item, host) {
    const card = document.createElement('article');
    card.className = 'card ytlc-search-card';
    card.dataset.chatVideoId = item.video_id;
    const body = document.createElement('div');
    body.className = 'body';
    const kind = document.createElement('div');
    kind.className = 'result-kind';
    kind.textContent = 'Live chat';
    const title = document.createElement('a');
    title.className = 'video-title';
    title.href = host.ui.localVideoHref(item.video_id);
    title.textContent = item.title || item.video_id;
    const summary = document.createElement('div');
    summary.className = 'details';
    summary.textContent = [
      formatCount(item.message_count, 'message'),
      formatCount(item.author_count, 'author'),
    ].join(' · ');
    const date = document.createElement('div');
    date.className = 'details';
    const dateValue = item.broadcast_ended_at || item.broadcast_started_at || item.completed_at;
    const dateLabel = item.broadcast_ended_at ? 'Broadcast ended'
      : item.broadcast_started_at ? 'Broadcast started' : 'Captured';
    date.textContent = `${dateLabel} ${host.ui.formatTime(dateValue)}`;
    body.append(kind, title, summary, date);
    const preview = document.createElement('div');
    preview.className = 'ytlc-search-preview';
    preview.append(...(item.messages || []).map(message => messageRow(
      item.video_id, message, item.authorChannels || new Map(), host, Boolean(item.query),
    )));
    body.append(preview);
    if (item.query) {
      const label = document.createElement('div');
      label.className = 'details';
      label.textContent = 'Matching message excerpts';
      body.append(label);
    }
    if (item.status === 'partial') {
      const partial = document.createElement('div');
      partial.className = 'details';
      partial.textContent = 'Partial capture';
      body.append(partial);
    }
    card.append(body);
    return card;
  }

  browserApi.register({
    id: 'live_chat',
    collection: {
      sorts: ['newest', 'oldest'],
      fetch: ({ query, limit, offset, sort, filters = {} }, host) => host.requestJson(
        'collection', { q: query, limit, offset, sort,
          own: filters.own === false ? '0' : '1', others: filters.others === false ? '0' : '1' },
      ),
    },
    search: {
      capability: 'video_live_chat_search',
      label: 'Live chats',
      serverResults: true,
      filters: [
        { key: 'own', label: 'own', hashParam: 'live-chat-own', disabledPreferenceKey: 'plugins.live_chat.filters.hide_own' },
        { key: 'others', label: 'others', hashParam: 'live-chat-others', disabledPreferenceKey: 'plugins.live_chat.filters.hide_others' },
      ],
      searchField: {
        key: 'live_chat', label: 'Live chats', defaultEnabled: true,
        appliesToKinds: ['videos'],
      },
      videoFacet: {
        presentLabel: 'live chats', absentLabel: 'no live chats',
        presentHashParam: 'with-live-chats', absentHashParam: 'without-live-chats',
        presentDisabledPreferenceKey: 'plugins.live_chat.filters.hide_present',
        absentDisabledPreferenceKey: 'plugins.live_chat.filters.hide_absent',
      },
      catalogCount: status => Number(status?.pluginStatus?.searchCatalogCount || 0),
      prepareResults: prepareSearchResults,
      renderResult: chatCard,
    },
    channelVideoTabs,
    entityCards: {
      capability: 'video_live_chat_availability',
      kinds: ['video'],
      prepare: prepareEntityCards,
      render: renderEntityCard,
    },
    videoDetail: {
      capability: 'video_live_chat_messages',
      render: renderVideoPanel,
    },
  });
})();
