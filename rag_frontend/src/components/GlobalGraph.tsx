import { useState, useEffect, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

interface Node {
  id: string;
  label: string;
  group: number;
}

interface Edge {
  source: string;
  target: string;
  value: number;
  label: string;
}

interface GraphData {
  nodes: Node[];
  links: Edge[];
}

const GlobalGraph = () => {
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchGraph = async () => {
      try {
        const response = await axios.get('http://localhost:8000/api/graph/global?threshold=0.15');
        // Backend returns {nodes, edges}, react-force-graph expects {nodes, links}
        setData({
          nodes: response.data.nodes,
          links: response.data.edges // axios call returns edges as edges, we map to links
        });
      } catch (error) {
        console.error('Failed to fetch global graph:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchGraph();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full w-full bg-[#0a0a0c]">
        <Loader2 className="animate-spin text-indigo-500 w-10 h-10" />
      </div>
    );
  }

  return (
    <div className="w-full h-full relative fade-in" ref={containerRef}>
      <div className="absolute top-6 left-6 z-10 glass p-4 rounded-xl max-w-sm pointer-events-none">
        <h2 className="text-xl font-bold mb-1">IND 知识全景图</h2>
        <p className="text-sm text-slate-400">展示各注册申报文件之间的语义关联度。单击节点可进入文件详情查看思维导图。</p>
      </div>

      <ForceGraph2D
        graphData={data}
        nodeLabel="id"
        nodeAutoColorBy="group"
        linkDirectionalParticles={2}
        linkDirectionalParticleSpeed={(d: any) => d.value * 0.005}
        nodeCanvasObject={(node: any, ctx, globalScale) => {
          const label = node.id;
          const fontSize = 12 / globalScale;
          ctx.font = `${fontSize}px Inter`;
          const textWidth = ctx.measureText(label).width;
          const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.2); // some padding

          ctx.fillStyle = 'rgba(10, 10, 12, 0.8)';
          ctx.beginPath();
          ctx.roundRect(node.x - bckgDimensions[0] / 2, node.y - node.val - bckgDimensions[1] - 2, bckgDimensions[0], bckgDimensions[1], 2);
          ctx.fill();

          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#e2e8f0';
          ctx.fillText(label, node.x, node.y - node.val - bckgDimensions[1] / 2 - 2);

          // Node circle
          const r = 4;
          ctx.beginPath();
          ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
          ctx.fillStyle = node.color || '#6366f1';
          ctx.fill();
          ctx.shadowBlur = 10;
          ctx.shadowColor = node.color || '#6366f1';
        }}
        onNodeClick={(node: any) => {
          navigate(`/file/${encodeURIComponent(node.id)}`);
        }}
        linkColor={() => 'rgba(255, 255, 255, 0.1)'}
        linkWidth={(d: any) => d.value * 2}
        backgroundColor="#0a0a0c"
      />
    </div>
  );
};

export default GlobalGraph;
