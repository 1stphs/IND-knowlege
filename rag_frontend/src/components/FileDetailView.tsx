import { useEffect, useMemo, useRef, useState, type WheelEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  Bot,
  FileSearch,
  Hash,
  Loader2,
  MessageCircleMore,
  Network,
  Search,
  Send,
  Sparkles,
  User,
  X,
} from 'lucide-react';

interface StructureNode {
  title: string;
  content: string;
  level: number;
  children?: StructureNode[];
}

interface FlatSection {
  id: string;
  title: string;
  content: string;
  level: number;
  preview: string;
  breadcrumb: string;
}

interface KGNode {
  id: string;
  label: string;
  type: 'Class' | 'Instance';
  group: number;
  description?: string;
  degree?: number;
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

interface RelatedDocument {
  source_md: string;
  overlap_count: number;
}

interface FileChunk {
  document_id: string;
  section_id: string;
  chunk_id: string;
  evidence_id: string;
  source_md: string;
  source_location: string;
  snippet: string;
}

interface FileDetailData {
  filename: string;
  document_id: string;
  keywords: string[];
  hf_words: string[];
  summary: string;
  structure: StructureNode[];
  chunks: FileChunk[];
  knowledge_graph: KGData;
  related_documents: RelatedDocument[];
  scope_documents: string[];
}

interface Citation {
  evidence_id: string;
  source_md?: string;
  source_location?: string;
  quote?: string;
  score?: number;
  evidence_type?: 'text' | 'graph' | string;
}

interface GraphPath {
  summary: string;
  evidence_id: string;
  source_md?: string;
  source_location?: string;
}

interface ChatMessage {
  role: 'user' | 'ai';
  content: string;
  citations?: Citation[];
  graph_paths?: GraphPath[];
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

interface EvidenceLocator {
  source_location?: string;
  source_context?: string;
  chunk_id?: string;
  evidence_id?: string;
}

interface PositionedNode extends KGNode {
  x: number;
  y: number;
  r: number;
}

interface PositionedLink extends KGLink {
  id: string;
  sourceId: string;
  targetId: string;
  sourceNode: PositionedNode;
  targetNode: PositionedNode;
}

function flattenStructure(items: StructureNode[], trail: string[] = []): FlatSection[] {
  return items.flatMap((item, index) => {
    const nextTrail = [...trail, item.title];
    const current: FlatSection = {
      id: `${nextTrail.join('>')}-${index}`,
      title: item.title,
      content: item.content || '',
      level: item.level || nextTrail.length,
      preview: (item.content || '').replace(/\s+/g, ' ').slice(0, 96),
      breadcrumb: nextTrail.join(' / '),
    };

    const children = flattenStructure(item.children || [], nextTrail);
    return [current, ...children];
  });
}

function getNodeId(node: string | KGNode) {
  return typeof node === 'string' ? node : node.id;
}

function normalizeSearchText(value: string | undefined) {
  return (value || '')
    .toLowerCase()
    .replace(/[#>*`"'“”‘’【】[\]{}()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function findBestSectionForEvidence(
  evidence: EvidenceLocator | null,
  sections: FlatSection[],
  chunks: FileChunk[],
): FlatSection | null {
  if (!evidence || sections.length === 0) {
    return null;
  }

  const normalizedLocation = normalizeSearchText(evidence.source_location);
  const normalizedContext = normalizeSearchText(evidence.source_context);
  const matchedChunk = chunks.find(
    (chunk) =>
      (evidence.chunk_id && chunk.chunk_id === evidence.chunk_id) ||
      (evidence.source_location && chunk.source_location === evidence.source_location),
  );
  const normalizedSnippet = normalizeSearchText(matchedChunk?.snippet);

  let bestSection: FlatSection | null = null;
  let bestScore = 0;

  for (const section of sections) {
    const title = normalizeSearchText(section.title);
    const breadcrumb = normalizeSearchText(section.breadcrumb);
    const content = normalizeSearchText(section.content).slice(0, 1200);
    let score = 0;

    if (normalizedLocation) {
      if (title && normalizedLocation.includes(title)) {
        score += 8;
      }
      if (breadcrumb && normalizedLocation.includes(breadcrumb)) {
        score += 12;
      }
      if (title && breadcrumb.includes(title) && normalizedLocation.includes(title)) {
        score += 4;
      }
    }

    if (normalizedContext && content) {
      if (content.includes(normalizedContext.slice(0, 80))) {
        score += 14;
      } else {
        const contextTokens = normalizedContext.split(' ').filter((token) => token.length >= 2).slice(0, 8);
        score += contextTokens.filter((token) => content.includes(token)).length * 2;
      }
    }

    if (normalizedSnippet && content) {
      if (content.includes(normalizedSnippet.slice(0, 80))) {
        score += 12;
      } else {
        const snippetTokens = normalizedSnippet.split(' ').filter((token) => token.length >= 2).slice(0, 8);
        score += snippetTokens.filter((token) => content.includes(token)).length * 2;
      }
    }

    if (score > bestScore) {
      bestScore = score;
      bestSection = section;
    }
  }

  return bestScore >= 6 ? bestSection : null;
}

function normalizeGraph(rawGraph: KGData | undefined): KGData {
  if (!rawGraph) {
    return { nodes: [], links: [] };
  }

  const degreeMap = new Map<string, number>();
  rawGraph.links.forEach((link) => {
    const sourceId = getNodeId(link.source);
    const targetId = getNodeId(link.target);
    degreeMap.set(sourceId, (degreeMap.get(sourceId) || 0) + 1);
    degreeMap.set(targetId, (degreeMap.get(targetId) || 0) + 1);
  });

  return {
    nodes: rawGraph.nodes.map((node) => ({
      ...node,
      degree: degreeMap.get(node.id) || 0,
    })),
    links: rawGraph.links.map((link) => ({
      ...link,
      source: getNodeId(link.source),
      target: getNodeId(link.target),
    })),
  };
}

function buildStaticGraphLayout(graphData: KGData) {
  const width = 720;
  const height = 440;
  const centerX = width / 2;
  const centerY = height / 2;
  const sortedNodes = [...graphData.nodes].sort(
    (left, right) => (right.degree || 0) - (left.degree || 0) || left.label.localeCompare(right.label),
  );

  const positionedNodes: PositionedNode[] = [];

  if (sortedNodes.length === 1) {
    positionedNodes.push({
      ...sortedNodes[0],
      x: centerX,
      y: centerY,
      r: 24,
    });
  } else if (sortedNodes.length > 1) {
    const ringCapacities = [6, 10, 14];
    const ringRadii = [118, 186, 246];

    positionedNodes.push({
      ...sortedNodes[0],
      x: centerX,
      y: centerY,
      r: 24 + Math.min((sortedNodes[0].degree || 0) * 0.8, 8),
    });

    let startIndex = 1;
    for (let ringIndex = 0; ringIndex < ringCapacities.length && startIndex < sortedNodes.length; ringIndex += 1) {
      const capacity = ringCapacities[ringIndex];
      const radius = ringRadii[ringIndex];
      const ringItems = sortedNodes.slice(startIndex, startIndex + capacity);

      ringItems.forEach((node, itemIndex) => {
        const angle = -Math.PI / 2 + (itemIndex / Math.max(ringItems.length, 1)) * Math.PI * 2;
        positionedNodes.push({
          ...node,
          x: centerX + Math.cos(angle) * radius,
          y: centerY + Math.sin(angle) * radius * 0.68,
          r: 16 + Math.min((node.degree || 0) * 0.55, 7),
        });
      });

      startIndex += capacity;
    }

    if (startIndex < sortedNodes.length) {
      const overflow = sortedNodes.slice(startIndex);
      overflow.forEach((node, index) => {
        const angle = -Math.PI / 2 + (index / Math.max(overflow.length, 1)) * Math.PI * 2;
        positionedNodes.push({
          ...node,
          x: centerX + Math.cos(angle) * 294,
          y: centerY + Math.sin(angle) * 294 * 0.68,
          r: 14 + Math.min((node.degree || 0) * 0.45, 6),
        });
      });
    }
  }

  const nodeMap = new Map(positionedNodes.map((node) => [node.id, node]));
  const positionedLinks: PositionedLink[] = graphData.links
    .map((link, index) => {
      const sourceId = getNodeId(link.source);
      const targetId = getNodeId(link.target);
      const sourceNode = nodeMap.get(sourceId);
      const targetNode = nodeMap.get(targetId);
      if (!sourceNode || !targetNode) {
        return null;
      }

      return {
        ...link,
        id: link.evidence_id || `${sourceId}_${link.label}_${targetId}_${index}`,
        sourceId,
        targetId,
        sourceNode,
        targetNode,
      };
    })
    .filter((item): item is PositionedLink => Boolean(item));

  return {
    width,
    height,
    nodes: positionedNodes,
    links: positionedLinks,
  };
}

const FileDetailView = () => {
  const { filename } = useParams();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [fileData, setFileData] = useState<FileDetailData | null>(null);
  const [selectedSection, setSelectedSection] = useState<FlatSection | null>(null);
  const [graphSearchInput, setGraphSearchInput] = useState('');
  const [graphSearchTerm, setGraphSearchTerm] = useState('');
  const [selectedNode, setSelectedNode] = useState<KGNode | null>(null);
  const [selectedLink, setSelectedLink] = useState<KGLink | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [scopeExpanded, setScopeExpanded] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const contentScrollRef = useRef<HTMLDivElement>(null);
  const structureItemRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const structureItems = useMemo(() => flattenStructure(fileData?.structure || []), [fileData?.structure]);
  const graphData = useMemo(() => normalizeGraph(fileData?.knowledge_graph), [fileData?.knowledge_graph]);
  const staticGraphLayout = useMemo(() => buildStaticGraphLayout(graphData), [graphData]);

  const relatedScopeDocuments = useMemo(() => {
    const scoped = fileData?.scope_documents || [];
    return Array.from(new Set(scoped));
  }, [fileData?.scope_documents]);

  const searchMatches = useMemo(() => {
    const normalizedTerm = graphSearchTerm.trim().toLowerCase();
    if (!normalizedTerm) {
      return [] as KGNode[];
    }

    return graphData.nodes.filter(
      (node) =>
        node.id.toLowerCase().includes(normalizedTerm) ||
        node.label.toLowerCase().includes(normalizedTerm) ||
        (node.description || '').toLowerCase().includes(normalizedTerm),
    );
  }, [graphData.nodes, graphSearchTerm]);

  const selectedNodeRelations = useMemo(() => {
    if (!selectedNode) {
      return [] as NodeRelationDetail[];
    }

    return graphData.links
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
      .slice(0, 16);
  }, [graphData.links, selectedNode]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await axios.get<FileDetailData>(
          `http://localhost:8000/api/file/details?filename=${encodeURIComponent(filename || '')}`,
          { timeout: 20000 },
        );

        const detailData = response.data;
        const initialSection = flattenStructure(detailData.structure || []).find((item) => item.content.trim()) || null;

        setFileData(detailData);
        setSelectedSection(
          initialSection || {
            id: detailData.document_id,
            title: detailData.filename,
            content: '当前文档没有可展示的正文结构，请查看右侧摘要或在文档问答中发起提问。',
            level: 1,
            preview: '',
            breadcrumb: detailData.filename,
          },
        );
        setChatMessages([
          {
            role: 'ai',
            content: `当前问答范围已经限定为《${detailData.filename}》以及 ${detailData.related_documents.length} 篇实体关联文档。您可以直接询问当前文档里的实体、关系、工艺步骤或证据出处。`,
          },
        ]);
      } catch (error) {
        console.error('Failed to fetch file details:', error);
      } finally {
        setLoading(false);
      }
    };

    if (filename) {
      fetchData();
    }
  }, [filename]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, chatOpen]);

  useEffect(() => {
    if (!selectedSection) {
      return;
    }

    structureItemRefs.current[selectedSection.id]?.scrollIntoView({
      block: 'center',
      behavior: 'smooth',
    });
    contentScrollRef.current?.scrollTo({
      top: 0,
      behavior: 'smooth',
    });
  }, [selectedSection]);

  const handleGraphSearch = () => {
    const normalizedTerm = graphSearchInput.trim();
    setGraphSearchTerm(normalizedTerm);
    if (!normalizedTerm) {
      return;
    }

    const matchedNode =
      graphData.nodes.find(
        (node) =>
          node.id.toLowerCase().includes(normalizedTerm.toLowerCase()) ||
          node.label.toLowerCase().includes(normalizedTerm.toLowerCase()) ||
          (node.description || '').toLowerCase().includes(normalizedTerm.toLowerCase()),
      ) || null;

    if (matchedNode) {
      setSelectedNode(matchedNode);
      setSelectedLink(null);
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

    if (graphSearchTerm.trim()) {
      return (
        searchMatches.some((node) => node.id === getNodeId(link.source)) ||
        searchMatches.some((node) => node.id === getNodeId(link.target))
      );
    }

    return false;
  };

  const selectEvidenceLink = (link: KGLink) => {
    setSelectedLink(link);
    setSelectedNode(null);

    const matchedSection = findBestSectionForEvidence(link, structureItems, fileData?.chunks || []);
    if (matchedSection) {
      setSelectedSection(matchedSection);
    }
  };

  const handleChatSend = async () => {
    if (!chatInput.trim() || chatLoading || !fileData) {
      return;
    }

    const userMessage = chatInput.trim();
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setChatLoading(true);

    try {
      const response = await axios.post(
        'http://localhost:8000/api/chat',
        {
          query: userMessage,
          top_k: 8,
          retrieval_options: {
            include_debug: false,
            source_mds: relatedScopeDocuments,
          },
        },
        { timeout: 45000 },
      );

      setChatMessages((prev) => [
        ...prev,
        {
          role: 'ai',
          content: response.data.answer,
          citations: response.data.citations,
          graph_paths: response.data.graph_paths,
        },
      ]);
    } catch (error) {
      console.error('Document scoped Q&A Error:', error);
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'ai',
          content: '当前文档问答暂时没有成功返回结果。请稍后重试，或换一个更具体的实体名称、关系词或章节标题。',
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleContentWheel = (event: WheelEvent<HTMLDivElement>) => {
    const container = contentScrollRef.current;
    if (!container) {
      return;
    }

    container.scrollTop += event.deltaY;
    event.preventDefault();
    event.stopPropagation();
  };

  if (loading) {
    return (
      <div className="detail-loading-shell">
        <Loader2 className="animate-spin text-blue-500 w-10 h-10" />
        <p>正在载入文档知识空间...</p>
      </div>
    );
  }

  return (
    <div className="detail-view-container fade-in document-detail-shell">
      <header className="detail-header">
        <button
          type="button"
          onClick={() => navigate('/knowledge-graph')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}
        >
          <ArrowLeft size={20} />
        </button>
        <div className="document-detail-title-wrap">
          <h1 className="document-detail-title">{fileData?.filename}</h1>
          <p className="document-detail-subtitle">左侧查看文档内实体图谱，中间浏览结构化原文，右侧保留摘要与关键词。</p>
        </div>
      </header>

      <div className="document-layout-grid">
        <aside className="document-graph-column">
          <div className="document-panel-card document-graph-card">
            <div className="document-panel-header">
              <div>
                <div className="document-panel-kicker">
                  <Network size={14} />
                  文档知识图谱
                </div>
                <h3>当前文档实体关系</h3>
              </div>
              <div className="document-panel-stat">
                节点 {graphData.nodes.length} · 关系 {graphData.links.length}
              </div>
            </div>

            <div className="document-graph-search">
              <Search size={15} />
              <input
                value={graphSearchInput}
                onChange={(event) => setGraphSearchInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    handleGraphSearch();
                  }
                }}
                placeholder="在当前文档图谱里搜索实体"
              />
              <button type="button" onClick={handleGraphSearch}>
                定位
              </button>
            </div>

            <div className="document-graph-wrap">
              {graphData.nodes.length === 0 ? (
                <div className="document-empty-state">
                  <div className="document-empty-orb" />
                  <p>当前文档还没有抽取到可展示的实体关系。</p>
                </div>
              ) : (
                <svg
                  className="document-static-graph"
                  viewBox={`0 0 ${staticGraphLayout.width} ${staticGraphLayout.height}`}
                  preserveAspectRatio="xMidYMid meet"
                >
                  <defs>
                    <linearGradient id="docLinkGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                      <stop offset="0%" stopColor="#94a3b8" stopOpacity="0.65" />
                      <stop offset="100%" stopColor="#334155" stopOpacity="0.78" />
                    </linearGradient>
                    <radialGradient id="docNodeBlue" cx="30%" cy="30%">
                      <stop offset="0%" stopColor="#dbeafe" />
                      <stop offset="55%" stopColor="#60a5fa" />
                      <stop offset="100%" stopColor="#1d4ed8" />
                    </radialGradient>
                    <radialGradient id="docNodeTeal" cx="30%" cy="30%">
                      <stop offset="0%" stopColor="#ccfbf1" />
                      <stop offset="55%" stopColor="#2dd4bf" />
                      <stop offset="100%" stopColor="#0f766e" />
                    </radialGradient>
                  </defs>

                  {staticGraphLayout.links.map((link) => {
                    const highlighted = isLinkHighlighted(link);
                    const midX = (link.sourceNode.x + link.targetNode.x) / 2;
                    const midY = (link.sourceNode.y + link.targetNode.y) / 2;
                    return (
                      <g key={link.id} className="document-static-link" onClick={() => selectEvidenceLink(link)}>
                        <line
                          x1={link.sourceNode.x}
                          y1={link.sourceNode.y}
                          x2={link.targetNode.x}
                          y2={link.targetNode.y}
                          stroke={highlighted ? '#0f172a' : 'url(#docLinkGrad)'}
                          strokeWidth={highlighted ? 3 : 2}
                          strokeLinecap="round"
                        />
                        {highlighted && (
                          <text x={midX} y={midY - 8} className="document-static-link-label">
                            {link.label}
                          </text>
                        )}
                      </g>
                    );
                  })}

                  {staticGraphLayout.nodes.map((node) => {
                    const isSelected = selectedNode?.id === node.id;
                    const isHovered = hoveredNodeId === node.id;
                    const isMatched = searchMatches.some((match) => match.id === node.id);
                    return (
                      <g
                        key={node.id}
                        className="document-static-node"
                        onMouseEnter={() => setHoveredNodeId(node.id)}
                        onMouseLeave={() => setHoveredNodeId(null)}
                        onClick={() => {
                          setSelectedNode(node);
                          setSelectedLink(null);
                        }}
                      >
                        <circle
                          cx={node.x}
                          cy={node.y}
                          r={node.r + 6}
                          fill={node.type === 'Class' ? 'rgba(37,99,235,0.12)' : 'rgba(20,184,166,0.14)'}
                        />
                        <circle
                          cx={node.x}
                          cy={node.y}
                          r={node.r}
                          fill={node.type === 'Class' ? 'url(#docNodeBlue)' : 'url(#docNodeTeal)'}
                          stroke={isSelected || isMatched ? '#0f172a' : 'rgba(255,255,255,0.9)'}
                          strokeWidth={isSelected || isMatched ? 2.5 : 1.5}
                        />
                        <circle
                          cx={node.x - node.r * 0.28}
                          cy={node.y - node.r * 0.32}
                          r={Math.max(2, node.r * 0.2)}
                          fill="rgba(255,255,255,0.72)"
                        />
                        <text x={node.x} y={node.y + node.r + 18} className="document-static-node-label">
                          {node.label}
                        </text>
                        {(isHovered || isSelected) && (
                          <text x={node.x} y={node.y - node.r - 12} className="document-static-node-meta">
                            关系 {node.degree || 0}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>
          </div>

          <div className="document-panel-card document-graph-detail-card">
            <div className="document-panel-header compact">
              <div>
                <div className="document-panel-kicker">
                  <Sparkles size={14} />
                  图谱详情
                </div>
                <h3>节点与关系证据</h3>
              </div>
            </div>

            {!selectedNode && !selectedLink && (
              <div className="document-graph-detail-empty">
                <p>点击左侧彩色球体查看实体三元组，点击连线查看实体之间的关联关系与证据出处。</p>
              </div>
            )}

            {selectedNode && (
              <div className="document-entity-detail">
                <div className="document-node-chip">实体节点</div>
                <h4>{selectedNode.label}</h4>
                <p className="document-muted">节点 ID：{selectedNode.id}</p>
                <p className="document-muted">关系数量：{selectedNode.degree || 0}</p>

                <div className="document-relations-list">
                  {selectedNodeRelations.length === 0 && <p className="document-muted">当前实体暂无关系证据。</p>}
                  {selectedNodeRelations.map((relation) => {
                    const isOutgoing = relation.sourceId === selectedNode.id;
                    return (
                      <button
                        key={relation.id}
                        type="button"
                        className="document-relation-chip"
                        onClick={() =>
                          selectEvidenceLink({
                            source: relation.sourceId,
                            target: relation.targetId,
                            label: relation.label,
                            value: 1,
                            source_context: relation.source_context,
                            source_location: relation.source_location,
                            source_md: relation.source_md,
                            chunk_id: relation.chunk_id,
                            evidence_id: relation.evidence_id,
                          })
                        }
                      >
                        <div className="document-relation-line">
                          {isOutgoing
                            ? `${relation.sourceId} --[${relation.label}]--> ${relation.targetId}`
                            : `${relation.sourceId} <--[${relation.label}]-- ${relation.targetId}`}
                        </div>
                        <div className="document-relation-meta">
                          {relation.source_md || '未知文档'} / {relation.source_location || '未知位置'}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {selectedLink && (
              <div className="document-entity-detail">
                <div className="document-node-chip relation">关系证据</div>
                <h4>{selectedLink.label}</h4>
                <p className="document-path-line">
                  {getNodeId(selectedLink.source)} → {getNodeId(selectedLink.target)}
                </p>
                {selectedLink.source_context && <div className="document-evidence-quote">“{selectedLink.source_context}”</div>}
                <div className="document-meta-grid">
                  <div>
                    <span>来源文档</span>
                    <strong>{selectedLink.source_md || '未知文档'}</strong>
                  </div>
                  <div>
                    <span>文档定位</span>
                    <strong>{selectedLink.source_location || '未知位置'}</strong>
                  </div>
                </div>
              </div>
            )}
          </div>
        </aside>

        <section className="document-center-column">
          <div className="document-panel-card document-structure-card">
            <div className="document-panel-header">
              <div>
                <div className="document-panel-kicker">
                  <BookOpen size={14} />
                  文档结构拆分
                </div>
                <h3>点击结构条目查看原文</h3>
              </div>
              <div className="document-panel-stat">结构节点 {structureItems.length}</div>
            </div>

            <div className="document-structure-workspace">
              <div className="document-structure-list">
                {structureItems.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className={`document-structure-item ${selectedSection?.id === section.id ? 'active' : ''}`}
                    onClick={() => setSelectedSection(section)}
                    ref={(element) => {
                      structureItemRefs.current[section.id] = element;
                    }}
                  >
                    <div className="document-structure-title" style={{ paddingLeft: `${Math.max(section.level - 1, 0) * 16}px` }}>
                      {section.title}
                    </div>
                    {section.preview && <div className="document-structure-preview">{section.preview}</div>}
                  </button>
                ))}
              </div>

              <div className="document-content-pane">
                <div className="document-content-pane-header">
                  <div>
                    <div className="document-panel-kicker">
                      <FileSearch size={14} />
                      原文定位
                    </div>
                    <h3>{selectedSection?.title || fileData?.filename}</h3>
                    <p>{selectedSection?.breadcrumb || fileData?.filename}</p>
                  </div>
                </div>

                <div className="document-content-scroll" ref={contentScrollRef} onWheel={handleContentWheel}>
                  {selectedSection?.content ? (
                    <div className="document-original-text">{selectedSection.content}</div>
                  ) : (
                    <div className="document-empty-state text-only">
                      <p>这个结构条目暂时没有可展示的正文内容。</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        <aside className="analytics-aside">
          <div style={{ marginBottom: '32px' }}>
            <h4
              style={{
                fontSize: '12px',
                fontWeight: '700',
                color: '#0f172a',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                textTransform: 'uppercase',
              }}
            >
              <Hash size={16} style={{ color: '#2563eb' }} /> 核心关键词
            </h4>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {fileData?.keywords?.map((kw: string, index: number) => (
                <span key={index} className="badge">
                  {kw}
                </span>
              ))}
            </div>
          </div>

          <div style={{ marginBottom: '32px' }}>
            <h4
              style={{
                fontSize: '12px',
                fontWeight: '700',
                color: '#0f172a',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                textTransform: 'uppercase',
              }}
            >
              <BarChart3 size={16} style={{ color: '#2563eb' }} /> 高频检索词
            </h4>
            <div>
              {fileData?.hf_words?.map((hw: string, index: number) => (
                <div
                  key={index}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '12px',
                    padding: '6px 0',
                    borderBottom: '1px solid rgba(148,163,184,0.16)',
                  }}
                >
                  <span style={{ color: '#475569' }}>{hw}</span>
                  <span style={{ color: '#2563eb', opacity: 0.85 }}>{(0.9 - index * 0.05).toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4
              style={{
                fontSize: '12px',
                fontWeight: '700',
                color: '#0f172a',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                textTransform: 'uppercase',
              }}
            >
              <BookOpen size={16} style={{ color: '#2563eb' }} /> 文档摘要
            </h4>
            <div
              style={{
                fontSize: '12px',
                color: '#475569',
                lineHeight: '1.7',
                background: 'rgba(255,255,255,0.78)',
                padding: '14px',
                borderRadius: '12px',
                border: '1px solid rgba(148,163,184,0.18)',
              }}
            >
              {fileData?.summary || '正在提取文档摘要...'}
            </div>
          </div>
        </aside>
      </div>

      <button type="button" className="doc-chat-fab" onClick={() => setChatOpen((prev) => !prev)} aria-label="打开文档问答">
        {chatOpen ? <X size={22} /> : <MessageCircleMore size={22} />}
      </button>

      <div className={`doc-chat-panel ${chatOpen ? 'open' : ''}`}>
        <div className="doc-chat-header">
          <div>
            <div className="document-panel-kicker">
              <Bot size={14} />
              文档作用域问答
            </div>
            <h3>当前文档 + 关联文档联合检索</h3>
            <p>
              当前文档 1 篇，关联文档 {fileData?.related_documents.length || 0} 篇，共 {relatedScopeDocuments.length} 篇纳入问答范围。
            </p>
          </div>
          <button type="button" className="doc-chat-close" onClick={() => setChatOpen(false)}>
            <X size={18} />
          </button>
        </div>

        <div className="doc-chat-scope">
          <button type="button" className="doc-scope-toggle" onClick={() => setScopeExpanded((prev) => !prev)}>
            {scopeExpanded ? '收起引用文档范围' : `展开引用文档范围（${relatedScopeDocuments.length}）`}
          </button>
          {scopeExpanded && (
            <div className="doc-scope-list">
              {relatedScopeDocuments.map((doc) => (
                <span key={doc} className="doc-scope-pill">
                  {doc}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="doc-chat-history">
          {chatMessages.map((message, index) => (
            <div key={index} className={`doc-chat-message ${message.role}`}>
              <div className="doc-chat-role">
                {message.role === 'user' ? (
                  <>
                    <User size={12} />
                    <span>用户</span>
                  </>
                ) : (
                  <>
                    <Bot size={12} />
                    <span>文档助手</span>
                  </>
                )}
              </div>
              <div className="doc-chat-bubble">{message.content}</div>

              {message.citations && message.citations.length > 0 && (
                <div className="doc-chat-evidence-group">
                  {message.citations.map((citation) => (
                    <button
                      key={citation.evidence_id}
                      type="button"
                      className="doc-chat-evidence-card"
                      onClick={() => citation.source_md && navigate(`/file/${encodeURIComponent(citation.source_md)}`)}
                    >
                      <div className="doc-chat-evidence-meta">
                        <span>
                          {citation.source_md || '未知文档'} / {citation.source_location || '未知位置'}
                        </span>
                        <span>{citation.evidence_type || 'text'}</span>
                      </div>
                      {citation.quote && <p>{citation.quote}</p>}
                    </button>
                  ))}
                </div>
              )}

              {message.graph_paths && message.graph_paths.length > 0 && (
                <div className="doc-chat-evidence-group">
                  {message.graph_paths.map((path) => (
                    <div key={`${path.evidence_id}-${path.summary}`} className="doc-chat-graph-card">
                      <div>{path.summary}</div>
                      <span>
                        {path.source_md || '未知文档'} / {path.source_location || '未知位置'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {chatLoading && (
            <div className="doc-chat-message ai">
              <div className="doc-chat-role">
                <Bot size={12} />
                <span>文档助手</span>
              </div>
              <div className="doc-chat-bubble loading">
                <Loader2 size={16} className="animate-spin" />
                <span>正在基于当前文档和关联文档检索证据...</span>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        <div className="doc-chat-input-row">
          <input
            type="text"
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                handleChatSend();
              }
            }}
            placeholder="例如：这个文档里的某个实体和哪些材料或工艺参数相关？"
          />
          <button type="button" onClick={handleChatSend} disabled={!chatInput.trim() || chatLoading}>
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default FileDetailView;

