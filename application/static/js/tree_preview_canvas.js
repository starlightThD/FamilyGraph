(() => {
  const mountEl = document.getElementById('tree-vue-app');
  if (!mountEl || !window.Vue) return;

  const treeId = Number(mountEl.dataset.treeId || 0);

  const NODE_WIDTH = 180;
  const NODE_HEIGHT = 56;
  const LEVEL_GAP = 140;
  const SIBLING_GAP = 28;
  const SPOUSE_GAP = 24;
  const MIN_SCALE = 0.2;
  const MAX_SCALE = 2.8;

  let uidSeq = 1;

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  const normalizeNode = (rawNode, edgeType) => ({
    id: rawNode.id,
    name: rawNode.name,
    generation: rawNode.generation,
    label: rawNode.label,
    node_type: rawNode.node_type,
    has_children: Boolean(rawNode.has_children),
    has_spouses: Boolean(rawNode.has_spouses),
    spouses: [],
    children: [],
    __edgeType: edgeType || null,
    __uid: `n${uidSeq++}`,
    __loaded: false,
    __loading: false,
    __expanded: false,
    __error: '',
    __subtreeWidth: NODE_WIDTH,
    __x: 0,
    __y: 0,
  });

  const isInternalNode = (node) => node && node.node_type === 'internal';

  const canExpandNode = (node) => {
    if (!isInternalNode(node)) return false;
    return Boolean(node.has_children || node.has_spouses);
  };

  const getVisibleDescendants = (node) => {
    if (!isInternalNode(node) || !node.__expanded || !node.__loaded) return [];
    return node.children;
  };

  const getVisibleSpouses = (node) => {
    if (!isInternalNode(node) || !node.__expanded || !node.__loaded) return [];
    return node.spouses;
  };

  const computeLayout = (rootNode) => {
    if (!rootNode) {
      return {
        nodes: [],
        edges: [],
        bounds: { minX: 0, maxX: 0, minY: 0, maxY: 0 },
      };
    }

    const nodes = [];
    const edges = [];

    const measure = (node) => {
      const spouses = getVisibleSpouses(node);
      const children = getVisibleDescendants(node);

      const rowWidth = NODE_WIDTH + spouses.length * (NODE_WIDTH + SPOUSE_GAP);
      node.__rowWidth = rowWidth;

      let childrenWidth = 0;
      children.forEach((child, index) => {
        childrenWidth += measure(child);
        if (index > 0) childrenWidth += SIBLING_GAP;
      });
      node.__childrenWidth = childrenWidth;

      node.__subtreeWidth = Math.max(NODE_WIDTH, rowWidth, childrenWidth);
      return node.__subtreeWidth;
    };

    const place = (node, left, depth) => {
      const rowLeft = left + (node.__subtreeWidth - node.__rowWidth) / 2;
      node.__x = rowLeft + NODE_WIDTH / 2;
      node.__y = depth * LEVEL_GAP;
      nodes.push(node);

      const spouses = getVisibleSpouses(node);
      spouses.forEach((spouse, index) => {
        spouse.__x = rowLeft + NODE_WIDTH + SPOUSE_GAP + index * (NODE_WIDTH + SPOUSE_GAP) + NODE_WIDTH / 2;
        spouse.__y = node.__y;
        nodes.push(spouse);
        edges.push({ from: node, to: spouse, edgeType: 'spouse' });
      });

      const children = getVisibleDescendants(node);
      if (!children.length) return;

      const parentAnchorX = rowLeft + node.__rowWidth / 2;
      let cursor = left + (node.__subtreeWidth - node.__childrenWidth) / 2;
      children.forEach((child) => {
        edges.push({
          from: node,
          to: child,
          edgeType: 'child',
          fromAnchorX: parentAnchorX,
        });
        place(child, cursor, depth + 1);
        cursor += child.__subtreeWidth + SIBLING_GAP;
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
      {
        minX: Infinity,
        maxX: -Infinity,
        minY: Infinity,
        maxY: -Infinity,
      },
    );

    return {
      nodes,
      edges,
      bounds: Number.isFinite(bounds.minX)
        ? bounds
        : { minX: 0, maxX: NODE_WIDTH, minY: 0, maxY: NODE_HEIGHT },
    };
  };

  const app = Vue.createApp({
    data() {
      return {
        treeId,
        autoExpandDepth: 2,
        loading: false,
        error: '',
        rootNode: null,
        viewport: {
          width: 960,
          height: 560,
        },
        camera: {
          x: 120,
          y: 120,
          scale: 1,
        },
        panning: {
          active: false,
          startX: 0,
          startY: 0,
          originX: 0,
          originY: 0,
        },
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
      visibleNodes() {
        return this.layout.nodes;
      },
      visibleEdges() {
        return this.layout.edges;
      },
      loadedNodeCount() {
        if (!this.rootNode) return 0;
        let count = 0;
        const walk = (node) => {
          count += 1;
          if (node.__loaded) {
            node.spouses.forEach((spouse) => {
              count += 1;
            });
            node.children.forEach((child) => walk(child));
          }
        };
        walk(this.rootNode);
        return count;
      },
    },
    async mounted() {
      await this.loadRoot();
      this.bindResizeObserver();
    },
    beforeUnmount() {
      if (this._resizeObserver) {
        this._resizeObserver.disconnect();
        this._resizeObserver = null;
      }
    },
    methods: {
      bindResizeObserver() {
        if (!this.$refs.viewport) return;
        const updateViewport = () => {
          const box = this.$refs.viewport.getBoundingClientRect();
          this.viewport.width = Math.max(320, Math.floor(box.width));
          this.viewport.height = Math.max(360, Math.floor(box.height));
          if (!this.hasManualViewportAction) {
            this.fitTreeToViewport();
          }
        };

        updateViewport();
        this._resizeObserver = new ResizeObserver(updateViewport);
        this._resizeObserver.observe(this.$refs.viewport);
      },
      edgePath(edge) {
        const fromX = edge.from.__x;
        const toX = edge.to.__x;

        if (edge.edgeType === 'spouse') {
          const direction = toX >= fromX ? 1 : -1;
          const startX = fromX + direction * (NODE_WIDTH / 2);
          const endX = toX - direction * (NODE_WIDTH / 2);
          const y = edge.from.__y;
          return `M ${startX} ${y} L ${endX} ${y}`;
        }

        const anchorX = edge.fromAnchorX != null ? edge.fromAnchorX : fromX;
        const fromY = edge.from.__y + NODE_HEIGHT / 2;
        const toY = edge.to.__y - NODE_HEIGHT / 2;
        const midY = fromY + (toY - fromY) * 0.45;
        return `M ${anchorX} ${fromY} L ${anchorX} ${midY} L ${toX} ${midY} L ${toX} ${toY}`;
      },
      isExpandable(node) {
        return canExpandNode(node);
      },
      async loadRoot() {
        if (!this.treeId) {
          this.error = 'Tree ID is required.';
          return;
        }

        this.loading = true;
        this.error = '';
        this.rootNode = null;

        try {
          const response = await fetch(`/api/tree-preview/root?tree_id=${this.treeId}`, { credentials: 'same-origin' });
          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Failed to load root node.');
          }

          this.rootNode = normalizeNode(payload.root, null);

          if (canExpandNode(this.rootNode) && this.autoExpandDepth > 0) {
            await this.expandNode(this.rootNode, 1, true);
          }

          this.$nextTick(() => {
            this.fitTreeToViewport();
          });
        } catch (error) {
          this.error = error && error.message ? error.message : 'Failed to load root node.';
        } finally {
          this.loading = false;
        }
      },
      async fetchBranch(node) {
        if (!node || !isInternalNode(node)) return;
        if (node.__loading || node.__loaded) return;

        node.__loading = true;
        node.__error = '';

        try {
          const response = await fetch(`/api/tree-preview/node/${node.id}/expand?tree_id=${this.treeId}`, {
            credentials: 'same-origin',
          });

          const payload = await response.json();
          if (!response.ok || !payload.ok) {
            throw new Error(payload.error || 'Failed to load node details.');
          }

          node.spouses = (payload.spouses || []).map((spouse) => normalizeNode(spouse, 'spouse'));
          node.children = (payload.children || []).map((child) => normalizeNode(child, 'child'));
          node.__loaded = true;
        } catch (error) {
          node.__error = error && error.message ? error.message : 'Failed to load node details.';
        } finally {
          node.__loading = false;
        }
      },
      async expandNode(node, depth, autoCascade) {
        if (!canExpandNode(node)) return;

        if (!node.__loaded) {
          await this.fetchBranch(node);
        }

        if (node.__error) return;

        node.__expanded = true;

        if (!autoCascade || depth >= this.autoExpandDepth) return;

        for (const child of node.children) {
          if (canExpandNode(child)) {
            await this.expandNode(child, depth + 1, true);
          }
        }
      },
      async toggleNode(node) {
        if (!canExpandNode(node)) return;

        if (node.__expanded) {
          node.__expanded = false;
          return;
        }

        await this.expandNode(node, 1, false);
      },
      zoomBy(factor) {
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
      onWheel(event) {
        event.preventDefault();
        if (!this.$refs.svg) return;

        const rect = this.$refs.svg.getBoundingClientRect();
        const px = event.clientX - rect.left;
        const py = event.clientY - rect.top;

        const deltaFactor = event.deltaY < 0 ? 1.1 : 0.9;
        const nextScale = clamp(this.camera.scale * deltaFactor, MIN_SCALE, MAX_SCALE);
        const wx = (px - this.camera.x) / this.camera.scale;
        const wy = (py - this.camera.y) / this.camera.scale;

        this.camera.scale = nextScale;
        this.camera.x = px - wx * nextScale;
        this.camera.y = py - wy * nextScale;
        this.hasManualViewportAction = true;
      },
      onPointerDown(event) {
        if (event.button !== 0) return;
        this.panning.active = true;
        this.panning.startX = event.clientX;
        this.panning.startY = event.clientY;
        this.panning.originX = this.camera.x;
        this.panning.originY = this.camera.y;
        if (this.$refs.svg) {
          this.$refs.svg.setPointerCapture(event.pointerId);
        }
      },
      onPointerMove(event) {
        if (!this.panning.active) return;
        this.camera.x = this.panning.originX + (event.clientX - this.panning.startX);
        this.camera.y = this.panning.originY + (event.clientY - this.panning.startY);
        this.hasManualViewportAction = true;
      },
      onPointerUp(event) {
        if (this.$refs.svg) {
          try {
            this.$refs.svg.releasePointerCapture(event.pointerId);
          } catch (error) {
            // Ignore capture release errors when pointer capture is already cleared.
          }
        }
        this.panning.active = false;
      },
      fitTreeToViewport() {
        if (!this.rootNode) return;

        const padding = 84;
        const bounds = this.layout.bounds;
        const contentWidth = Math.max(1, bounds.maxX - bounds.minX);
        const contentHeight = Math.max(1, bounds.maxY - bounds.minY);

        const scaleX = (this.viewport.width - padding * 2) / contentWidth;
        const scaleY = (this.viewport.height - padding * 2) / contentHeight;
        const nextScale = clamp(Math.min(scaleX, scaleY, 1.35), MIN_SCALE, MAX_SCALE);

        this.camera.scale = nextScale;
        this.camera.x = (this.viewport.width - contentWidth * nextScale) / 2 - bounds.minX * nextScale;
        this.camera.y = (this.viewport.height - contentHeight * nextScale) / 2 - bounds.minY * nextScale;
      },
      resetViewport() {
        this.hasManualViewportAction = false;
        this.fitTreeToViewport();
      },
      nodeTitle(node) {
        if (!isInternalNode(node)) {
          return 'Spouse node';
        }
        if (!canExpandNode(node)) {
          return 'No descendants or spouses to expand';
        }
        if (node.__loading) {
          return 'Loading descendants';
        }
        return node.__expanded ? 'Click to collapse' : 'Click to expand';
      },
      nodeLabel(node) {
        return node.label || node.name || 'Unknown';
      },
    },
    template: `
      <div>
        <div v-if="loading" class="result-box">Loading root node...</div>
        <div v-else-if="error" class="alert"><span v-text="error"></span></div>
        <div v-else-if="rootNode" class="tree-canvas-shell">
          <div class="tree-toolbar">
            <div class="tree-toolbar-group">
              <button type="button" class="btn small ghost" @click="zoomBy(1.12)">Zoom In</button>
              <button type="button" class="btn small ghost" @click="zoomBy(0.88)">Zoom Out</button>
              <button type="button" class="btn small" @click="resetViewport">Fit Tree</button>
            </div>
            <div class="tree-toolbar-meta">
              <span>Visible: {{ visibleNodes.length }} nodes</span>
              <span>Loaded: {{ loadedNodeCount }} nodes</span>
              <span>Scale: {{ Math.round(camera.scale * 100) }}%</span>
            </div>
          </div>

          <div ref="viewport" class="tree-canvas-viewport">
            <svg
              ref="svg"
              class="tree-canvas"
              :class="{ panning: panning.active }"
              :width="viewport.width"
              :height="viewport.height"
              @wheel="onWheel"
              @pointerdown="onPointerDown"
              @pointermove="onPointerMove"
              @pointerup="onPointerUp"
              @pointercancel="onPointerUp"
              @pointerleave="onPointerUp"
            >
              <g :transform="cameraTransform">
                <path
                  v-for="(edge, index) in visibleEdges"
                  :key="'edge-' + index"
                  :d="edgePath(edge)"
                  :class="['tree-edge', edge.edgeType === 'spouse' ? 'spouse-edge' : 'child-edge']"
                />

                <g
                  v-for="node in visibleNodes"
                  :key="node.__uid"
                  :transform="'translate(' + (node.__x - 90) + ' ' + (node.__y - 28) + ')'"
                  @pointerdown.stop
                  @click.stop="toggleNode(node)"
                >
                  <rect
                    x="0"
                    y="0"
                    width="180"
                    height="56"
                    rx="11"
                    ry="11"
                    :class="[
                      'tree-card',
                      node.node_type === 'internal' ? 'tree-card-internal' : 'tree-card-spouse',
                      isExpandable(node) ? 'tree-card-expandable' : ''
                    ]"
                  />
                  <text x="90" y="24" class="tree-card-label" text-anchor="middle">{{ nodeLabel(node).slice(0, 20) }}</text>
                  <text x="90" y="42" class="tree-card-meta" text-anchor="middle">
                    {{ node.__error ? 'Load failed' : (node.node_type === 'internal' ? 'Member' : 'Spouse') }}
                  </text>

                  <g v-if="isExpandable(node)">
                    <circle cx="166" cy="14" r="10" class="tree-toggle-dot" />
                    <text x="166" y="18" class="tree-toggle-symbol" text-anchor="middle">{{ node.__expanded ? '-' : '+' }}</text>
                  </g>

                  <g v-if="node.__loading">
                    <circle cx="14" cy="14" r="8" class="tree-loading-dot" />
                  </g>

                  <title>{{ nodeTitle(node) }}</title>
                </g>
              </g>
            </svg>
          </div>

          <div class="tree-hint">Tip: drag canvas to pan, mouse wheel to zoom, click green nodes to expand/collapse.</div>
        </div>
        <div v-else class="result-box">No tree data available.</div>
      </div>
    `,
  });

  app.mount('#tree-vue-app');
})();
