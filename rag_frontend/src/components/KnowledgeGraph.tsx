import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import axios from 'axios';
import { Database, ExternalLink, Loader2, Search, Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';

interface KGNode {
  id: string;
  label: string;
  type: 'Class' | 'Instance';
  group: number;
  description?: string;
  degree?: number;
  val?: number;
  color?: string;
}

interface KGLink {
  source: string | KGNode;
  target: string | KGNode;
  label: string;
  value: number;
  source_context?: string;
  source_location?: string;
  source_md?: string;
  chunk_id?: string;
  evidence_id?: string;
}

interface KGData {
  nodes: KGNode[];
  links: KGLink[];
}

interface GraphStats {
  totalNodes: number;
  totalLinks: number;
}

interface NodeRelationDetail {
  id: string;
  sourceId: string;
  targetId: string;
  label: string;
  source_md?: string;
  source_location?: string;
  source_context?: string;
  chunk_id?: string;
  evidence_id?: string;
}

function getNodeId(node: string | KGNode) {
  return typeof node === 'string' ? node : node.id;
}

const KnowledgeGraph = () => {
  const [data, setData] = useState<KGData>({ nodes: [], links: [] });
  const [stats, setStats] = useState<GraphStats>({ totalNodes: 0, totalLinks: 0 });
  const [loading, setLoading] = useState(true);
  const [searchInput, setSearchInput] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null);
  const [selectedLink, setSelectedLink] = useState<KGLink | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);

  useEffect(() => {
    const fetchKG = async () => {
      try {
        const response = await axios.get('http://localhost:8000/api/graph/knowledge', {
          timeout: 20000,
        });

        const rawData = response.data as KGData;
        const degreeMap = new Map<string, number>();
        rawData.links.forEach((link) => {
          const sourceId = getNodeId(link.source);
          const targetId = getNodeId(link.target);
          degreeMap.set(sourceId, (degreeMap.get(sourceId) || 0) + 1);
          degreeMap.set(targetId, (degreeMap.get(targetId) || 0) + 1);
        });

        const normalizedNodes = rawData.nodes.map((node) => {
          const degree = degreeMap.get(node.id) || 0;
          return {
            ...node,
            degree,
            val: node.type === 'Class' ? 11 : 10 + Math.min(degree * 0.45, 10),
            color: node.type === 'Class' ? '#2563eb' : '#14b8a6',
          };
        });

        const normalizedLinks = rawData.links.map((link) => ({
          ...link,
          source: getNodeId(link.source),
          target: getNodeId(link.target),
        }));

        setData({
          nodes: normalizedNodes,
          links: normalizedLinks,
        });
        setStats({
          totalNodes: normalizedNodes.length,
          totalLinks: normalizedLinks.length,
        });
      } catch (error) {
        console.error('Failed to fetch knowledge graph:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchKG();
  }, []);

  const searchMatches = useMemo(() => {
    const normalizedTerm = searchTerm.trim().toLowerCase();
    if (!normalizedTerm) {
      return [] as KGNode[];
    }
    return data.nodes.filter(
      (node) =>
        node.id.toLowerCase().includes(normalizedTerm) ||
        node.label.toLowerCase().includes(normalizedTerm) ||
        (node.description || '').toLowerCase().includes(normalizedTerm),
    );
  }, [data.nodes, searchTerm]);

  const selectedNodeRelations = useMemo(() => {
    if (!selectedNode) {
      return [] as NodeRelationDetail[];
    }

    return data.links
      .filter((link) => getNodeId(link.source) === selectedNode.id || getNodeId(link.target) === selectedNode.id)
      .map((link, index) => ({
        id: link.evidence_id || `${getNodeId(link.source)}_${link.label}_${getNodeId(link.target)}_${index}`,
        sourceId: getNodeId(link.source),
        targetId: getNodeId(link.target),
        label: link.label,
        source_md: link.source_md,
        source_location: link.source_location,
        source_context: link.source_context,
        chunk_id: link.chunk_id,
        evidence_id: link.evidence_id,
      }))
      .slice(0, 18);
  }, [data.links, selectedNode]);

  useEffect(() => {
    if (!graphRef.current || data.nodes.length === 0) {
      return;
    }

    const chargeForce = graphRef.current.d3Force('charge');
    if (chargeForce?.strength) {
      chargeForce.strength(-165);
    }

    const linkForce = graphRef.current.d3Force('link');
    if (linkForce?.distance) {
      linkForce.distance((link: KGLink) => {
        const sourceNode = data.nodes.find((node) => node.id === getNodeId(link.source));
        const targetNode = data.nodes.find((node) => node.id === getNodeId(link.target));
        const degreeWeight = Math.max(sourceNode?.degree || 1, targetNode?.degree || 1);
        return 90 + Math.min(degreeWeight * 4, 54);
      });
    }

    const fitTimer = window.setTimeout(() => {
      graphRef.current?.zoomToFit(600, 60);
    }, 250);

    return () => window.clearTimeout(fitTimer);
  }, [data.nodes, data.links]);

  const focusNode = (node: KGNode | null) => {
    if (!node || !graphRef.current) {
      return;
    }

    const tryFocus = (attempt = 0) => {
      if (typeof (node as any).x === 'number' && typeof (node as any).y === 'number') {
        graphRef.current.centerAt((node as any).x, (node as any).y, 600);
        graphRef.current.zoom(2.3, 600);
        return;
      }

      if (attempt < 8) {
        window.setTimeout(() => tryFocus(attempt + 1), 120);
      }
    };

    tryFocus();
  };

  const handleSearch = () => {
    const normalizedTerm = searchInput.trim();
    setSearchTerm(normalizedTerm);
    if (!normalizedTerm) {
      return;
    }

    const matchedNode = data.nodes.find(
      (node) =>
        node.id.toLowerCase().includes(normalizedTerm.toLowerCase()) ||
        node.label.toLowerCase().includes(normalizedTerm.toLowerCase()) ||
        (node.description || '').toLowerCase().includes(normalizedTerm.toLowerCase()),
    );

    if (matchedNode) {
      setSelectedNode(matchedNode);
      setSelectedLink(null);
      focusNode(matchedNode);
    }
  };

  const isLinkHighlighted = (link: KGLink) => {
    if (selectedLink) {
      return (
        getNodeId(selectedLink.source) === getNodeId(link.source) &&
        getNodeId(selectedLink.target) === getNodeId(link.target) &&
        selectedLink.label === link.label
      );
    }

    if (selectedNode) {
      return getNodeId(link.source) === selectedNode.id || getNodeId(link.target) === selectedNode.id;
    }

    if (searchTerm.trim()) {
      return (
        searchMatches.some((node) => node.id === getNodeId(link.source)) ||
        searchMatches.some((node) => node.id === getNodeId(link.target))
      );
    }

    return false;
  };

  if (loading) {
    return (
      <div className="kg-shell">
        <div className="kg-loading-card">
          <Loader2 className="animate-spin text-blue-500 w-10 h-10" />
          <p>正在载入实体知识图谱...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="kg-shell">
      <div className="kg-stage">
        <div className="kg-hero-card">
          <div className="kg-hero-badge">
            <Sparkles size={14} />
            实体知识图谱
          </div>
          <h1>搜索实体后直接定位，点击节点和连线查看证据</h1>
          <p>当前图谱支持本体实体搜寻、画布自动定位、节点右侧详情和关系证据展示，同时保持现有渲染链路稳定。</p>
        </div>

        <div className="kg-toolbar">
          <div className="kg-search">
            <Search size={16} />
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  handleSearch();
                }
              }}
              placeholder="搜索本体实体、药物代号或关系词"
            />
            <button type="button" className="kg-canvas-btn" onClick={handleSearch}>
              定位
            </button>
          </div>
          <div className="kg-stat-pill">
            <Database size={14} />
            节点 {stats.totalNodes}
          </div>
          <div className="kg-stat-pill">关系 {stats.totalLinks}</div>
          <div className="kg-stat-pill">命中 {searchMatches.length}</div>
        </div>

        <div className="kg-main-card">
          <div className="kg-force-wrap" ref={containerRef}>
            <div className="kg-canvas-meta">
              <span>拖动画布平移</span>
              <span>滚轮缩放</span>
              <span>点击节点或连线看详情</span>
            </div>

            <ForceGraph2D
              ref={graphRef}
              graphData={data}
              backgroundColor="rgba(0,0,0,0)"
              cooldownTicks={80}
              warmupTicks={35}
              nodeRelSize={8}
              linkDirectionalArrowLength={6}
              linkDirectionalArrowRelPos={1}
              linkCurvature={0.16}
              linkLabel={(link: any) => link.label}
              linkWidth={(link: KGLink) => (isLinkHighlighted(link) ? 2.8 : 1.7)}
              linkColor={(link: KGLink) => (isLinkHighlighted(link) ? 'rgba(15, 23, 42, 0.82)' : 'rgba(30, 41, 59, 0.42)')}
              onNodeHover={(node) => setHoveredNodeId((node as KGNode | null)?.id || null)}
              onNodeClick={(node: any) => {
                setSelectedNode(node);
                setSelectedLink(null);
                focusNode(node);
              }}
              onLinkClick={(link: any) => {
                setSelectedLink(link);
                setSelectedNode(null);
              }}
              nodeCanvasObject={(node: any, ctx, globalScale) => {
                if (!Number.isFinite(node.x) || !Number.isFinite(node.y) || !Number.isFinite(globalScale)) {
                  return;
                }

                const typedNode = node as KGNode;
                const radius = typedNode.type === 'Class' ? 12 : 10 + Math.min((typedNode.degree || 0) * 0.38, 8);
                const isSelected = selectedNode?.id === typedNode.id;
                const isHovered = hoveredNodeId === typedNode.id;
                const isMatched = searchMatches.some((match) => match.id === typedNode.id);
                const shouldShowLabel = isSelected || isHovered || isMatched || globalScale > 1.7;

                ctx.save();

                ctx.beginPath();
                ctx.arc(node.x, node.y, radius + 6, 0, 2 * Math.PI, false);
                ctx.fillStyle = typedNode.type === 'Class' ? 'rgba(37, 99, 235, 0.15)' : 'rgba(20, 184, 166, 0.15)';
                ctx.fill();

                const gradient = ctx.createRadialGradient(
                  node.x - radius * 0.4,
                  node.y - radius * 0.55,
                  radius * 0.2,
                  node.x,
                  node.y,
                  radius * 1.15,
                );
                if (typedNode.type === 'Class') {
                  gradient.addColorStop(0, '#dbeafe');
                  gradient.addColorStop(0.52, '#60a5fa');
                  gradient.addColorStop(1, '#1d4ed8');
                } else {
                  gradient.addColorStop(0, '#ccfbf1');
                  gradient.addColorStop(0.5, '#2dd4bf');
                  gradient.addColorStop(1, '#0f766e');
                }

                ctx.beginPath();
                ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
                ctx.shadowBlur = isSelected || isMatched ? 24 : 14;
                ctx.shadowColor = typedNode.type === 'Class' ? 'rgba(37, 99, 235, 0.38)' : 'rgba(13, 148, 136, 0.32)';
                ctx.fillStyle = gradient;
                ctx.fill();
                ctx.shadowBlur = 0;

                ctx.beginPath();
                ctx.arc(node.x - radius * 0.3, node.y - radius * 0.34, Math.max(2, radius * 0.22), 0, 2 * Math.PI, false);
                ctx.fillStyle = 'rgba(255,255,255,0.7)';
                ctx.fill();

                if (isSelected || isMatched) {
                  ctx.beginPath();
                  ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI, false);
                  ctx.strokeStyle = '#0f172a';
                  ctx.lineWidth = 2;
                  ctx.stroke();
                }

                if (shouldShowLabel) {
                  const fontSize = Math.max(12, 13 / globalScale);
                  const label = typedNode.label;
                  ctx.font = `600 ${fontSize}px "Segoe UI", "PingFang SC", sans-serif`;
                  const textWidth = ctx.measureText(label).width;
                  const textX = node.x;
                  const textY = node.y + radius + fontSize + 10;

                  ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
                  ctx.beginPath();
                  ctx.roundRect(textX - textWidth / 2 - 8, textY - fontSize, textWidth + 16, fontSize + 10, 10);
                  ctx.fill();

                  ctx.textAlign = 'center';
                  ctx.textBaseline = 'middle';
                  ctx.fillStyle = '#111827';
                  ctx.fillText(label, textX, textY - fontSize / 2 + 5);
                }

                ctx.restore();
              }}
            />
          </div>
        </div>
      </div>

      <aside className="kg-side-panel">
        <div className="kg-side-header">
          <h2>图谱详情</h2>
          {(selectedNode || selectedLink) && (
            <button
              className="kg-clear-btn"
              onClick={() => {
                setSelectedNode(null);
                setSelectedLink(null);
              }}
            >
              清空
            </button>
          )}
        </div>

        {!selectedNode && !selectedLink && (
          <div className="kg-empty-state">
            <div className="kg-empty-orb" />
            <p>点击彩色球体查看实体详情，点击连线查看实体之间的关联关系和证据来源。</p>
          </div>
        )}

        {selectedNode && (
          <div className="kg-detail-card">
            <div className="kg-node-chip">{selectedNode.type === 'Class' ? '本体类' : '实例节点'}</div>
            <h3>{selectedNode.label}</h3>
            <p className="kg-muted">节点 ID：{selectedNode.id}</p>
            <p className="kg-muted">连接度：{selectedNode.degree || 0}</p>
            {selectedNode.description && <div className="kg-note">{selectedNode.description}</div>}

            <div className="kg-node-relations">
              <h4>关联三元组</h4>
              {selectedNodeRelations.length === 0 && <p className="kg-muted">当前节点暂无可展示的关系证据。</p>}
              {selectedNodeRelations.map((relation) => {
                const isOutgoing = relation.sourceId === selectedNode.id;
                return (
                  <button
                    key={relation.id}
                    type="button"
                    className="kg-relation-item"
                    onClick={() => {
                      setSelectedNode(null);
                      setSelectedLink({
                        source: relation.sourceId,
                        target: relation.targetId,
                        label: relation.label,
                        value: 1,
                        source_context: relation.source_context,
                        source_location: relation.source_location,
                        source_md: relation.source_md,
                        chunk_id: relation.chunk_id,
                        evidence_id: relation.evidence_id,
                      });
                    }}
                  >
                    <div className="kg-relation-line">
                      {isOutgoing
                        ? `${relation.sourceId} --[${relation.label}]--> ${relation.targetId}`
                        : `${relation.sourceId} <--[${relation.label}]-- ${relation.targetId}`}
                    </div>
                    <div className="kg-relation-meta">
                      {relation.source_md || '未知文档'} / {relation.source_location || '未知位置'}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {selectedLink && (
          <div className="kg-detail-card">
            <div className="kg-node-chip kg-link-chip">关联关系</div>
            <h3>{selectedLink.label}</h3>
            <p className="kg-path-text">
              {getNodeId(selectedLink.source)} → {getNodeId(selectedLink.target)}
            </p>
            {selectedLink.source_context && <div className="kg-quote">“{selectedLink.source_context}”</div>}
            <div className="kg-metadata-grid">
              <div>
                <span>来源文档</span>
                <strong>{selectedLink.source_md || '未知文档'}</strong>
              </div>
              <div>
                <span>定位位置</span>
                <strong>{selectedLink.source_location || '未知位置'}</strong>
              </div>
            </div>
            {selectedLink.source_md && (
              <Link className="kg-link-btn" to={`/file/${encodeURIComponent(selectedLink.source_md)}`}>
                查看原文详情
                <ExternalLink size={14} />
              </Link>
            )}
          </div>
        )}
      </aside>
    </div>
  );
};

export default KnowledgeGraph;
