(() => {
  const mountEl = document.getElementById('descendant-tree-vue-app');
  if (!mountEl || !window.Vue) return;

  const personId = Number(mountEl.dataset.personId || 0);
  const maxDepthRaw = (mountEl.dataset.maxDepth || '').trim();
  const maxDepth = maxDepthRaw ? Number(maxDepthRaw) : null;

  const NODE_WIDTH = 216;
  const NODE_HEIGHT = 58;
  const LEVEL_GAP_X = 250;
  const SIBLING_GAP_Y = 24;
  const MIN_SCALE = 0.2;
  const MAX_SCALE = 2.6;

  let uidSeq = 1;
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  const normalizeNode = (rawNode) => ({
    id: rawNode.id,
    name: rawNode.name,
    generation: rawNode.generation,
    gender: rawNode.gender || 'unknown',
    depth: Number(rawNode.depth || 0),
    label: rawNode.label || rawNode.name || 'Unknown',
    has_children: Boolean(rawNode.has_children),
    path_ids: Array.isArray(rawNode.path_ids) ? rawNode.path_ids : [rawNode.id],
    children: [],
    __uid: `dp${uidSeq++}`,
    __loaded: false,
    __loading: false,
    __expanded: false,
    __error: '',
    __x: 0,
    __y: 0,
    __subtreeHeight: NODE_HEIGHT,
  });

  const getVisibleChildren = (node) => {
    if (!node || !node.__expanded || !node.__loaded) return [];
    return node.children;
  };

  const canExpandNode = (node) => Boolean(node && node.has_children);

  const computeLayout = (rootNode) => {
    if (!rootNode) {
      return {
        nodes: [],
        edges: [],
        bounds: { minX: 0, maxX: NODE_WIDTH, minY: 0, maxY: NODE_HEIGHT },
      };
    }

    const nodes = [];
    const edges = [];

    const measure = (node) => {
      const children = getVisibleChildren(node);
      if (!children.length) {
        node.__subtreeHeight = NODE_HEIGHT;
        return NODE_HEIGHT;
      }

      let total = 0;
      children.forEach((child, index) => {
        total += measure(child);
        if (index > 0) total += SIBLING_GAP_Y;
      });
      node.__subtreeHeight = Math.max(NODE_HEIGHT, total);
      return node.__subtreeHeight;
    };

    const place = (node, depth, top) => {
      node.__x = depth * LEVEL_GAP_X;
      node.__y = top + node.__subtreeHeight / 2;
      nodes.push(node);

      const children = getVisibleChildren(node);
      if (!children.length) return;

      const childrenTotalHeight = children.reduce((sum, child, index) => {
        return sum + child.__subtreeHeight + (index > 0 ? SIBLING_GAP_Y : 0);
      }, 0);

      let cursor = top + (node.__subtreeHeight - childrenTotalHeight) / 2;
      children.forEach((child) => {
        edges.push({ from: node, to: child });
        place(child, depth + 1, cursor);
        cursor += child.__subtreeHeight + SIBLING_GAP_Y;
      });
    };

    measure(rootNode);
    place(rootNode, 0, 0);

    const bounds = nodes.reduce(
      (acc, node) => {
        const minX = node.__x - NODE_WIDTH / 2;
        const maxX = node.__x + NODE_WIDTH / 2;
        const minY = node.__y - NODE_HEIGHT / 2;
        const maxY = node.__y + NODE_HEIGHT / 2;
        return {
          minX: Math.min(acc.minX, minX),
          maxX: Math.max(acc.maxX, maxX),
          minY: Math.min(acc.minY, minY),
          maxY: Math.max(acc.maxY, maxY),
        };
      },
      { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity },
    );

    if (!Number.isFinite(bounds.minX)) {
      return {
        nodes,
        edges,
        bounds: { minX: 0, maxX: NODE_WIDTH, minY: 0, maxY: NODE_HEIGHT },
      };
    }

    return { nodes, edges, bounds };
  };

  const app = Vue.createApp({
    data() {
      return {
        personId,
        maxDepth: Number.isFinite(maxDepth) ? maxDepth : null,
        loading: false,
        error: '',
        rootNode: null,
        viewport: { width: 1100, height: 560 },
        camera: { x: 80, y: 80, scale: 1 },
        panning: { active: false, sx: 0, sy: 0, ox: 0, oy: 0 },
        hasManualViewportAction: false,
      };
    },
    computed: {
      layout() {
        return computeLayout(this.rootNode);
      },
      cameraTransform() {
        return `translate(${this.camera.x} ${this.camera.y}) scale(${this.camera.scale})`;
      },
      loadedNodeCount() {
        if (!this.rootNode) return 0;
        let count = 0;
        const walk = (node) => {
          count += 1;
          if (node.__loaded) {
            node.children.forEach((child) => walk(child));
          }
        };
        walk(this.rootNode);
        return count;
      },
    },
    async mounted() {
      await this.loadRoot();
      this.bindResize();
    },
    beforeUnmount() {
      if (this._resizeObserver) {
        this._resizeObserver.disconnect();
        this._resizeObserver = null;
      }
    },
    methods: {
      canExpandNode(node) {
        return canExpandNode(node);
      },
      bindResize() {
        if (!this.$refs.viewport) return;
        const update = () => {
          const box = this.$refs.viewport.getBoundingClientRect();
          this.viewport.width = Math.max(360, Math.floor(box.width));
          this.viewport.height = Math.max(380, Math.floor(box.height));
          if (!this.hasManualViewportAction) this.fit();
        };

        update();
        this._resizeObserver = new ResizeObserver(update);
        this._resizeObserver.observe(this.$refs.viewport);
      },
      edgePath(edge) {
        const fromX = edge.from.__x + NODE_WIDTH / 2;
        const fromY = edge.from.__y;
        const toX = edge.to.__x - NODE_WIDTH / 2;
        const toY = edge.to.__y;
        const midX = fromX + (toX - fromX) * 0.45;
        return `M ${fromX} ${fromY} L ${midX} ${fromY} L ${midX} ${toY} L ${toX} ${toY}`;
      },
      nodeLabel(node) {
        const text = node.label || node.name || 'Unknown';
        return text.length > 28 ? `${text.slice(0, 28)}...` : text;
      },
      nodeTitle(node) {
        if (!canExpandNode(node)) {
          return 'No more direct descendants';
        }
        if (node.__loading) return 'Loading descendants';
        return node.__expanded ? 'Click to collapse' : 'Click to expand';
      },
      async loadRoot() {
        if (!this.personId) {
          this.error = 'Person ID is required.';
          return;
        }

        this.loading = true;
        this.error = '';
        this.rootNode = null;

        try {
          const params = new URLSearchParams({ person_id: String(this.personId) });
          if (this.maxDepth != null) {
            params.set('max_depth', String(this.maxDepth));
          }
          const response = await fetch(`/api/patriline-preview/root?${params.toString()}`, {
            credentials: 'same-origin',
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Failed to load root node.');
          }
          this.rootNode = normalizeNode(payload.root);
          this.$nextTick(() => this.fit());
        } catch (error) {
          this.error = error && error.message ? error.message : 'Failed to load root node.';
        } finally {
          this.loading = false;
        }
      },
      async fetchChildren(node) {
        if (!node || node.__loading || node.__loaded) return;

        node.__loading = true;
        node.__error = '';
        try {
          const params = new URLSearchParams({
            root_id: String(this.personId),
            path: node.path_ids.join(','),
          });
          if (this.maxDepth != null) {
            params.set('max_depth', String(this.maxDepth));
          }

          const response = await fetch(`/api/patriline-preview/node/${node.id}/expand?${params.toString()}`, {
            credentials: 'same-origin',
          });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Failed to load descendants.');
          }

          node.children = (payload.children || []).map((child) => normalizeNode(child));
          node.__loaded = true;
          if (!node.children.length) {
            node.has_children = false;
          }
        } catch (error) {
          node.__error = error && error.message ? error.message : 'Failed to load descendants.';
        } finally {
          node.__loading = false;
        }
      },
      async toggleNode(node) {
        if (!canExpandNode(node)) return;

        if (node.__expanded) {
          node.__expanded = false;
          return;
        }

        if (!node.__loaded) {
          await this.fetchChildren(node);
        }
        if (node.__error) return;
        node.__expanded = true;
      },
      wheel(event) {
        event.preventDefault();
        const rect = this.$refs.svg.getBoundingClientRect();
        const px = event.clientX - rect.left;
        const py = event.clientY - rect.top;
        const factor = event.deltaY < 0 ? 1.1 : 0.9;
        const nextScale = clamp(this.camera.scale * factor, MIN_SCALE, MAX_SCALE);
        const wx = (px - this.camera.x) / this.camera.scale;
        const wy = (py - this.camera.y) / this.camera.scale;

        this.camera.scale = nextScale;
        this.camera.x = px - wx * nextScale;
        this.camera.y = py - wy * nextScale;
        this.hasManualViewportAction = true;
      },
      down(event) {
        if (event.button !== 0) return;
        this.panning.active = true;
        this.panning.sx = event.clientX;
        this.panning.sy = event.clientY;
        this.panning.ox = this.camera.x;
        this.panning.oy = this.camera.y;
        this.$refs.svg.setPointerCapture(event.pointerId);
      },
      move(event) {
        if (!this.panning.active) return;
        this.camera.x = this.panning.ox + (event.clientX - this.panning.sx);
        this.camera.y = this.panning.oy + (event.clientY - this.panning.sy);
        this.hasManualViewportAction = true;
      },
      up(event) {
        if (this.$refs.svg) {
          try {
            this.$refs.svg.releasePointerCapture(event.pointerId);
          } catch (error) {
            // noop
          }
        }
        this.panning.active = false;
      },
      zoom(factor) {
        const nextScale = clamp(this.camera.scale * factor, MIN_SCALE, MAX_SCALE);
        if (nextScale === this.camera.scale) return;
        const cx = this.viewport.width / 2;
        const cy = this.viewport.height / 2;
        const wx = (cx - this.camera.x) / this.camera.scale;
        const wy = (cy - this.camera.y) / this.camera.scale;
        this.camera.scale = nextScale;
        this.camera.x = cx - wx * nextScale;
        this.camera.y = cy - wy * nextScale;
        this.hasManualViewportAction = true;
      },
      fit() {
        const { minX, maxX, minY, maxY } = this.layout.bounds;
        const w = Math.max(1, maxX - minX);
        const h = Math.max(1, maxY - minY);
        const padding = 72;
        const sx = (this.viewport.width - padding * 2) / w;
        const sy = (this.viewport.height - padding * 2) / h;
        const nextScale = clamp(Math.min(sx, sy, 1.25), MIN_SCALE, MAX_SCALE);

        this.camera.scale = nextScale;
        this.camera.x = (this.viewport.width - w * nextScale) / 2 - minX * nextScale;
        this.camera.y = (this.viewport.height - h * nextScale) / 2 - minY * nextScale;
      },
      reset() {
        this.hasManualViewportAction = false;
        this.fit();
      },
      cardClass(node) {
        return [
          'ancestor-card',
          node.depth === 0 ? 'ancestor-root-card' : 'ancestor-parent-card',
          canExpandNode(node) ? 'ancestor-card-expandable' : '',
        ];
      },
    },
    template: `
      <div>
        <div v-if="loading" class="result-box">Loading root node...</div>
        <div v-else-if="error" class="alert"><span v-text="error"></span></div>
        <div v-else-if="rootNode">
          <div class="tree-toolbar">
            <div class="tree-toolbar-group">
              <button type="button" class="btn small ghost" @click="zoom(1.12)">Zoom In</button>
              <button type="button" class="btn small ghost" @click="zoom(0.88)">Zoom Out</button>
              <button type="button" class="btn small" @click="reset">Fit Graph</button>
            </div>
            <div class="tree-toolbar-meta">
              <span>Visible: {{ layout.nodes.length }} nodes</span>
              <span>Loaded: {{ loadedNodeCount }} nodes</span>
              <span>Scale: {{ Math.round(camera.scale * 100) }}%</span>
            </div>
          </div>

          <div ref="viewport" class="ancestor-canvas-viewport">
            <svg
              ref="svg"
              class="ancestor-canvas"
              :class="{ panning: panning.active }"
              :width="viewport.width"
              :height="viewport.height"
              @wheel="wheel"
              @pointerdown="down"
              @pointermove="move"
              @pointerup="up"
              @pointercancel="up"
              @pointerleave="up"
            >
              <g :transform="cameraTransform">
                <path v-for="(edge, idx) in layout.edges" :key="'de-' + idx" :d="edgePath(edge)" class="ancestor-edge" />

                <g
                  v-for="node in layout.nodes"
                  :key="node.__uid"
                  :transform="'translate(' + (node.__x - 108) + ' ' + (node.__y - 29) + ')'"
                  @pointerdown.stop
                  @click.stop="toggleNode(node)"
                >
                  <rect
                    x="0"
                    y="0"
                    width="216"
                    height="58"
                    rx="12"
                    ry="12"
                    :class="cardClass(node)"
                  />
                  <text x="108" y="24" class="ancestor-card-label" text-anchor="middle">{{ nodeLabel(node) }}</text>
                  <text x="108" y="43" class="ancestor-card-meta" text-anchor="middle">
                    {{ node.__error ? 'Load failed' : ('Depth ' + node.depth + ' · ' + node.gender) }}
                  </text>

                  <g v-if="canExpandNode(node)">
                    <circle cx="194" cy="14" r="10" class="tree-toggle-dot" />
                    <text x="194" y="18" class="tree-toggle-symbol" text-anchor="middle">{{ node.__expanded ? '-' : '+' }}</text>
                  </g>

                  <g v-if="node.__loading">
                    <circle cx="14" cy="14" r="8" class="tree-loading-dot" />
                  </g>

                  <title>{{ nodeTitle(node) }}</title>
                </g>
              </g>
            </svg>
          </div>

          <div class="tree-hint">Tip: click nodes to expand direct descendants, drag to pan, wheel to zoom.</div>
        </div>
        <div v-else class="result-box">No descendant tree data available.</div>
      </div>
    `,
  });

  app.mount('#descendant-tree-vue-app');
})();
