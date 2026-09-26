(() => {
  if (!document.body) return null;

  const state = window.__brownie ||= {
    ids: new WeakMap(),
    nodes: new Map(),
    nextId: 1,
  };
  const nodeId = element => {
    if (!state.ids.has(element)) state.ids.set(element, state.nextId++);
    const id = state.ids.get(element);
    state.nodes.set(id, element);
    return id;
  };
  for (const [id, element] of state.nodes) {
    if (!element.isConnected) state.nodes.delete(id);
  }

  const closestComposed = (element, selector) => {
    let current = element;
    while (current) {
      const match = current.closest?.(selector);
      if (match) return match;
      const root = current.getRootNode?.();
      current = root instanceof ShadowRoot ? root.host : null;
    }
    return null;
  };
  const visible = element => {
    if (closestComposed(element, '[aria-hidden="true"],[inert]')) return false;
    if (element.checkVisibility) {
      return element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
    }
    const style = getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) !== 0;
  };
  const inViewport = rect =>
    rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight &&
    rect.right > 0 && rect.left < innerWidth;
  const roots = [document];
  for (let offset = 0; offset < roots.length; offset += 1) {
    for (const element of roots[offset].querySelectorAll('*')) {
      if (element.shadowRoot) roots.push(element.shadowRoot);
    }
  }

  const accessibleName = (element, seen = new Set()) => {
    if (!element || seen.has(element)) return '';
    seen.add(element);
    const root = element.getRootNode?.() || document;
    const labelledBy = (element.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .filter(Boolean)
      .map(id => accessibleName(root.getElementById?.(id) || document.getElementById(id), seen))
      .filter(Boolean)
      .join(' ');
    return labelledBy || element.getAttribute('aria-label') ||
      [...(element.labels || [])].map(label => accessibleName(label, seen)).filter(Boolean).join(' ') ||
      (['button', 'submit', 'reset'].includes(element.type) ? element.value : '') ||
      element.getAttribute('alt') ||
      (element.tagName === 'INPUT' ? '' : element.innerText?.trim()) ||
      element.getAttribute('title') || element.getAttribute('placeholder') || '';
  };

  const supportedRoles = [
    'button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem',
    'menuitemradio', 'option', 'gridcell', 'combobox', 'textbox', 'searchbox',
    'spinbutton',
  ];
  const selector = [
    'a[href]', 'button', 'input', 'textarea', 'select', 'summary',
    '[contenteditable="true"]', ...supportedRoles.map(role => `[role="${role}"]`),
  ].join(',');
  const roleOf = element => {
    const explicit = element.getAttribute('role');
    if (supportedRoles.includes(explicit)) return explicit;
    if (element.tagName === 'BUTTON' || element.tagName === 'SUMMARY') return 'button';
    if (element.tagName === 'A') return 'link';
    if (element.tagName === 'SELECT') return 'combobox';
    if (element.tagName === 'TEXTAREA' || element.isContentEditable) return 'textbox';
    if (element.tagName === 'INPUT') {
      if (['checkbox', 'radio'].includes(element.type)) return element.type;
      if (['button', 'submit', 'reset', 'image'].includes(element.type)) return 'button';
      if (element.type === 'search') return 'searchbox';
      if (element.type === 'number') return 'spinbutton';
      if (['text', 'email', 'url', 'tel'].includes(element.type)) return 'textbox';
    }
    return null;
  };
  const operationsFor = (element, role) => {
    const editable = !element.readOnly && element.getAttribute('aria-readonly') !== 'true' &&
      (['textbox', 'searchbox', 'spinbutton'].includes(role) ||
        (role === 'combobox' && ['INPUT', 'TEXTAREA'].includes(element.tagName)));
    if (!editable) return ['CLICK'];
    return element.form ? ['CLICK', 'TYPE_TEXT', 'SUBMIT'] : ['CLICK', 'TYPE_TEXT'];
  };
  const destinationFor = element => {
    if (element.tagName !== 'A' || !element.href) return '';
    const destination = new URL(element.href, location.href);
    if (destination.origin === location.origin) {
      const pathname = location.protocol === 'file:'
        ? destination.pathname.replace(/^\/[A-Za-z]:/, '')
        : destination.pathname;
      return `${pathname}${destination.search}`;
    }
    return `${destination.origin}${destination.pathname}`;
  };
  const contextFor = (element, name) => {
    const parts = [];
    const root = element.getRootNode?.();
    if (root instanceof ShadowRoot) {
      const hostName = accessibleName(root.host) || root.host.id || root.host.tagName.toLowerCase();
      parts.push(`shadow: ${hostName}`);
    }
    if (element.tagName === 'A') {
      const list = element.closest('ul,ol');
      const numberedLinks = list
        ? [...list.querySelectorAll('a[href]')].filter(link => /^\d+$/.test(accessibleName(link).trim()))
        : [];
      if (numberedLinks.length >= 2) parts.push('pagination');
      else {
        const navigation = element.closest('nav,[role="navigation"]');
        if (navigation) parts.push((accessibleName(navigation) || 'navigation').slice(0, 180));
        else {
          const container = element.closest('article,li,tr,[role="listitem"]');
          const nearby = container?.innerText?.replace(/\s+/g, ' ').trim() || '';
          if (nearby && nearby !== name) parts.push(nearby.slice(0, 180));
        }
      }
    }
    return parts.join(' · ');
  };

  const elements = [];
  for (const root of roots) {
    for (const element of root.querySelectorAll(selector)) {
      if (['password', 'file', 'hidden'].includes(element.type)) continue;
      if (!visible(element) || element.matches(':disabled') || closestComposed(element, '[aria-disabled="true"]')) continue;
      const rect = element.getBoundingClientRect();
      const role = roleOf(element);
      if (!role || !inViewport(rect)) continue;
      const name = accessibleName(element) || role;
      elements.push({
        node_id: nodeId(element),
        role,
        name,
        value: 'value' in element ? String(element.value) : '',
        checked: 'checked' in element ? Boolean(element.checked) : null,
        operations: operationsFor(element, role),
        context: contextFor(element, name),
        destination: destinationFor(element),
      });
    }
  }

  const textParts = [];
  const range = document.createRange();
  let textLength = 0;
  for (const root of roots) {
    const walker = document.createTreeWalker(root === document ? document.body : root, NodeFilter.SHOW_TEXT);
    let textNode;
    while ((textNode = walker.nextNode()) && textLength < 6000) {
      const value = textNode.textContent.trim();
      const parent = textNode.parentElement;
      if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(textNode);
      if (!inViewport(range.getBoundingClientRect())) continue;
      textParts.push(value);
      textLength += value.length;
    }
    if (textLength >= 6000) break;
  }

  const limit = 100;
  const omittedElements = Math.max(0, elements.length - limit);
  const indexedElements = elements.slice(0, limit).map((element, offset) => ({
    index: offset + 1,
    ...element,
  }));
  const documentHeight = document.documentElement.scrollHeight;
  const allPasswordFields = roots.flatMap(root => [...root.querySelectorAll('input[type="password"]')]);
  const visiblePasswordField = allPasswordFields
    .some(element => visible(element) && inViewport(element.getBoundingClientRect()));
  const frames = roots.flatMap(root => [...root.querySelectorAll('iframe,frame')]);
  const challengeMarker = roots.some(root => Boolean(root.querySelector(
    'iframe[src*="challenges.cloudflare.com"],.cf-turnstile,[name="cf-turnstile-response"]'
  )));
  return {
    url: location.href,
    title: document.title,
    viewport: {width: innerWidth, height: innerHeight, scroll_y: scrollY, document_height: documentHeight},
    text: textParts.join('\n').slice(0, 6000),
    elements: indexedElements,
    access: {
      visible_password_field: visiblePasswordField,
      password_field_present: allPasswordFields.length > 0,
      challenge_marker: challengeMarker,
    },
    perception: {
      surface: 'document_and_open_shadow_viewport_dom',
      frame_count: frames.length,
      visible_frame_count: frames.filter(frame => visible(frame) && inViewport(frame.getBoundingClientRect())).length,
      inspected_frame_count: 0,
      inaccessible_frame_count: 0,
      open_shadow_root_count: roots.length - 1,
      inspected_open_shadow_root_count: roots.length - 1,
      accessibility_fallback_used: false,
      accessibility_limit_reached: false,
      accessibility_unavailable_count: 0,
      text_limit_reached: textLength >= 6000,
      element_limit_reached: omittedElements > 0,
    },
    omitted_elements: omittedElements,
    can_scroll_up: scrollY > 0,
    can_scroll_down: scrollY + innerHeight < documentHeight - 2,
  };
})()
