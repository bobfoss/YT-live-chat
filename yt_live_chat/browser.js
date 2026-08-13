(() => {
  'use strict';

  const browserApi = window.YTLibraryBrowserPlugins;
  if (!browserApi || browserApi.apiVersion !== 2 || browserApi.features?.entityCards !== 1) {
    return;
  }

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

  function messageRow(videoId, message, authorChannels, host) {
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
    text.textContent = String(message.messageText || '');
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

  async function loadMessagePage(panel, host, append) {
    if (panel.dataset.ytlcLoading === 'true') return;
    const videoId = panel.dataset.ytlcVideo || '';
    const messages = panel.querySelector('.ytlc-messages');
    const status = panel.querySelector('.ytlc-message-status');
    const button = panel.querySelector('[data-ytlc-more]');
    if (!videoId || !(messages instanceof HTMLElement)) return;
    const offset = append ? Number(panel.dataset.ytlcNextOffset || 0) : 0;
    panel.dataset.ytlcLoading = 'true';
    if (button instanceof HTMLButtonElement) button.disabled = true;
    if (status instanceof HTMLElement) status.textContent = 'Loading recorded chat...';
    try {
      const payload = await host.requestJson(
        `videos/${encodeURIComponent(videoId)}/messages`,
        { limit: 250, offset },
      );
      const pageMessages = payload.messages || [];
      const authorChannels = await resolveAuthorChannels(pageMessages, host);
      if (!append) messages.replaceChildren();
      messages.append(...pageMessages.map(
        message => messageRow(videoId, message, authorChannels, host),
      ));
      const loaded = Number(payload.offset || 0) + pageMessages.length;
      const total = Number(payload.total || loaded);
      panel.dataset.ytlcNextOffset = String(loaded);
      if (status instanceof HTMLElement) {
        status.textContent = total
          ? `${loaded.toLocaleString()} of ${total.toLocaleString()} messages`
          : 'This capture contains no user messages.';
      }
      if (button instanceof HTMLButtonElement) button.hidden = loaded >= total;
    } catch (error) {
      if (status instanceof HTMLElement) {
        status.textContent = error instanceof Error ? error.message : String(error);
      }
    } finally {
      panel.dataset.ytlcLoading = 'false';
      if (button instanceof HTMLButtonElement) button.disabled = false;
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
    const status = document.createElement('div');
    status.className = 'ytlc-message-status';
    status.setAttribute('aria-live', 'polite');
    const messages = document.createElement('div');
    messages.className = 'ytlc-messages';
    const loadMore = document.createElement('button');
    loadMore.type = 'button';
    loadMore.className = 'ytlc-load-more';
    loadMore.dataset.ytlcMore = '';
    loadMore.textContent = 'Load more';
    loadMore.hidden = true;
    content.append(status, messages, loadMore);
    panel.append(heading, content);

    panel.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const toggleButton = target.closest('[data-ytlc-toggle]');
      if (toggleButton instanceof HTMLButtonElement) {
        const expanded = toggleButton.getAttribute('aria-expanded') === 'true';
        setExpanded(panel, !expanded);
        if (!expanded && !panel.querySelector('.ytlc-message')) {
          void loadMessagePage(panel, host, false);
        }
        return;
      }
      const moreButton = target.closest('[data-ytlc-more]');
      if (moreButton instanceof HTMLButtonElement) {
        void loadMessagePage(panel, host, true);
      }
    });
    return panel;
  }

  browserApi.register({
    id: 'live_chat',
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
