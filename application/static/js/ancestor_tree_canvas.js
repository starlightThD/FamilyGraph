(() => {
  const mountEl = document.getElementById('ancestor-tree-canvas');
  const dataEl = document.getElementById('ancestor-tree-data');
  if (!mountEl || !dataEl || !window.Vue) return;

  let treeData;
  try {
    treeData = JSON.parse(dataEl.textContent || '{}');
  } catch (error) {
    mountEl.innerHTML = '<div class="alert">Failed to parse ancestor tree data.</div>';
    return;
  }

  const NODE_WIDTH = 216;
  const NODE_HEIGHT = 58;
  const LEVEL_GAP_X = 250;
  const SIBLING_GAP_Y = 24;
  const MIN_SCALE = 0.2;
  const MAX_SCALE = 2.6;

  let uid = 0;

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

  const normalize = (node) => ({
    __uid: `a${uid++}`,
    name: node.name || 'Unknown',
    children: Array.isArray(node.children) ? node.children.map(normalize) : [],
    __x: 0,
    __y: 0,
    __subtreeHeight: NODE_HEIGHT,
  });

  const root = normalize(treeData || {});

  const computeLayout = () => {
    const nodes = [];
    const edges = [];

    const measure = (node) => {
      if (!node.children.length) {
        node.__subtreeHeight = NODE_HEIGHT;
        return node.__subtreeHeight;
      }

      let total = 0;
      node.children.forEach((child, index) => {
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

      let cursor = top + (node.__subtreeHeight - node.children.reduce((sum, child, idx) => {
        return sum + child.__subtreeHeight + (idx > 0 ? SIBLING_GAP_Y : 0);
      }, 0)) / 2;

      node.children.forEach((child) => {
        edges.push({ from: node, to: child });
        place(child, depth + 1, cursor);
        cursor += child.__subtreeHeight + SIBLING_GAP_Y;
      });
    };

    measure(root);
    place(root, 0, 0);

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

    return {
      nodes,
      edges,
      bounds,
    };
  };

  const app = Vue.createApp({
    data() {
      return {
        viewport: { width: 1100, height: 560 },
        camera: { x: 80, y: 80, scale: 1 },
        panning: { active: false, sx: 0, sy: 0, ox: 0, oy: 0 },
        hasManualViewportAction: false,
      };
    },
    computed: {
      layout() {
        return computeLayout();
      },
      cameraTransform() {
        return `translate(${this.camera.x} ${this.camera.y}) scale(${this.camera.scale})`;
      },
    },
    mounted() {
      this.bindResize();
      this.fit();
    },
    beforeUnmount() {
      if (this._resizeObserver) {
        this._resizeObserver.disconnect();
      }
    },
    methods: {
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
      label(node) {
        return node.name.length > 28 ? `${node.name.slice(0, 28)}...` : node.name;
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
    },
    template: `
      <div>
        <div class="tree-toolbar">
          <div class="tree-toolbar-group">
            <button type="button" class="btn small ghost" @click="zoom(1.12)">Zoom In</button>
            <button type="button" class="btn small ghost" @click="zoom(0.88)">Zoom Out</button>
            <button type="button" class="btn small" @click="reset">Fit Graph</button>
          </div>
          <div class="tree-toolbar-meta">
            <span>Nodes: {{ layout.nodes.length }}</span>
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
              <path v-for="(edge, idx) in layout.edges" :key="'ae-' + idx" :d="edgePath(edge)" class="ancestor-edge" />

              <g
                v-for="(node, index) in layout.nodes"
                :key="node.__uid"
                :transform="'translate(' + (node.__x - 108) + ' ' + (node.__y - 29) + ')'"
              >
                <rect
                  x="0"
                  y="0"
                  width="216"
                  height="58"
                  rx="12"
                  ry="12"
                  :class="['ancestor-card', index === 0 ? 'ancestor-root-card' : 'ancestor-parent-card']"
                />
                <text x="108" y="35" class="ancestor-card-label" text-anchor="middle">{{ label(node) }}</text>
                <title>{{ node.name }}</title>
              </g>
            </g>
          </svg>
        </div>

        <div class="tree-hint">Tip: drag to pan, wheel to zoom. Left-most node is the selected person, right side are ancestors.</div>
      </div>
    `,
  });

  app.mount('#ancestor-tree-canvas');
})();
