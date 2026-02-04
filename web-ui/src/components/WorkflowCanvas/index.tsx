import { useCallback, useMemo, useEffect, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
  BackgroundVariant,
} from 'reactflow';
import { useAppStore } from '../../stores/appStore';
import { AgentNode } from './AgentNode';
import { NodeDetailPanel } from './NodeDetailPanel';
import { ExecutionSelector } from '../ExecutionSelector';
import { wsService } from '../../services/websocket';
import type { NodeExecutionResult } from '../../types';

// 自定义节点类型
const nodeTypes = {
  agent: AgentNode,
};

// 智能 DAG 布局算法
function dagLayout(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return [];

  // 构建依赖图
  const inDegree: Record<string, number> = {};
  const outEdges: Record<string, string[]> = {};

  nodes.forEach(n => {
    inDegree[n.id] = 0;
    outEdges[n.id] = [];
  });

  edges.forEach(e => {
    if (inDegree[e.target] !== undefined) {
      inDegree[e.target]++;
    }
    if (outEdges[e.source]) {
      outEdges[e.source].push(e.target);
    }
  });

  // 拓扑排序分层
  const layers: string[][] = [];
  const visited = new Set<string>();
  const nodeLayer: Record<string, number> = {};

  // BFS 分层
  let currentLayer = nodes.filter(n => inDegree[n.id] === 0).map(n => n.id);

  while (currentLayer.length > 0) {
    layers.push(currentLayer);
    currentLayer.forEach(id => {
      visited.add(id);
      nodeLayer[id] = layers.length - 1;
    });

    const nextLayer: string[] = [];
    currentLayer.forEach(id => {
      outEdges[id]?.forEach(targetId => {
        if (!visited.has(targetId)) {
          inDegree[targetId]--;
          if (inDegree[targetId] === 0) {
            nextLayer.push(targetId);
          }
        }
      });
    });
    currentLayer = nextLayer;
  }

  // 处理未访问的节点（可能有环或孤立节点）
  nodes.forEach(n => {
    if (!visited.has(n.id)) {
      if (layers.length === 0) layers.push([]);
      layers[layers.length - 1].push(n.id);
      nodeLayer[n.id] = layers.length - 1;
    }
  });

  // 布局参数 - 更大的间距
  const LAYER_HEIGHT = 160;
  const NODE_WIDTH = 260;
  const HORIZONTAL_GAP = 40;
  const START_Y = 60;

  // 计算每层的宽度和位置
  const nodePositions: Record<string, { x: number; y: number }> = {};

  layers.forEach((layer, layerIndex) => {
    const layerWidth = layer.length * NODE_WIDTH + (layer.length - 1) * HORIZONTAL_GAP;
    const startX = -layerWidth / 2 + NODE_WIDTH / 2;

    layer.forEach((nodeId, nodeIndex) => {
      nodePositions[nodeId] = {
        x: startX + nodeIndex * (NODE_WIDTH + HORIZONTAL_GAP),
        y: START_Y + layerIndex * LAYER_HEIGHT,
      };
    });
  });

  // 应用位置
  return nodes.map(node => ({
    ...node,
    position: nodePositions[node.id] || { x: 0, y: 0 },
  }));
}

export function WorkflowCanvas() {
  const {
    workflowState,
    highlightedNodes,
    nodeStates,
    executionProgress,
    selectedExecutionId,
    currentExecutionDetail,
  } = useAppStore();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // 计算是否为历史模式
  const isHistoryMode = selectedExecutionId !== null;

  // 监听执行选择变化，请求执行详情
  useEffect(() => {
    if (selectedExecutionId) {
      wsService.getExecutionDetail(selectedExecutionId);
    }
  }, [selectedExecutionId]);

  // 将工作流状态转换为 ReactFlow 格式
  const { flowNodes, flowEdges } = useMemo(() => {
    if (!workflowState?.nodes) return { flowNodes: [], flowEdges: [] };

    const isPreviewMode = workflowState.nodes?.some(n => n.nodeType === 'preview' || n.status === 'preview');

    // 构建节点
    const nodes: Node[] = workflowState.nodes.map((node) => {
      const nodeState = nodeStates[node.nodeId];
      const isHighlighted = highlightedNodes.includes(node.nodeId);
      const isCurrentNode = executionProgress.currentNode === node.nodeId;
      const isPreview = node.nodeType === 'preview' || node.status === 'preview';
      const agent = workflowState.agents?.find(a => a.agentId === node.agentId);

      // 优先使用 displayName，回退到 agent 的 displayName，最后使用 name
      const displayLabel = node.displayName || agent?.displayName || node.name;

      // 计算状态和耗时
      let status = nodeState?.status || node.status || (isPreview ? 'preview' : 'pending');
      let duration = nodeState?.duration;

      // 历史模式：使用执行详情中的状态
      if (isHistoryMode && currentExecutionDetail?.nodeResults) {
        const nodeResults = currentExecutionDetail.nodeResults as Record<string, { status?: string; durationMs?: number }>;
        // 通过 workflowNodeId 查找
        const nodeResult = node.workflowNodeId ? nodeResults[node.workflowNodeId] : undefined;
        if (nodeResult) {
          status = nodeResult.status || status;
          duration = nodeResult.durationMs;
        }
      }

      return {
        id: node.nodeId,
        type: 'agent',
        position: { x: 0, y: 0 },
        data: {
          label: displayLabel,
          nodeType: node.nodeType,
          status,
          duration,
          agent,
          isHighlighted,
          isCurrentNode,
          description: node.description,
          tools: node.tools,
          dependencies: node.dependencies,
        },
      };
    });

    // 构建边 - 优雅的贝塞尔曲线
    const edges: Edge[] = (workflowState.edges || []).map((edge) => {
      const isContextRef = edge.edgeType === 'context_ref';
      const sourceCompleted = nodeStates[edge.source]?.status === 'completed';
      const targetRunning = nodeStates[edge.target]?.status === 'running';

      return {
        id: `e-${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        type: 'default', // 使用默认贝塞尔曲线
        animated: !isPreviewMode && sourceCompleted && targetRunning,
        style: {
          stroke: isPreviewMode
            ? (isContextRef ? '#94a3b8' : '#60a5fa')
            : (sourceCompleted ? '#10b981' : '#cbd5e1'),
          strokeWidth: isContextRef ? 1 : 2,
          strokeDasharray: isContextRef ? '6 4' : '0',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 16,
          height: 16,
          color: isPreviewMode
            ? (isContextRef ? '#94a3b8' : '#60a5fa')
            : (sourceCompleted ? '#10b981' : '#cbd5e1'),
        },
      };
    });

    // 应用 DAG 布局
    const layoutedNodes = dagLayout(nodes, edges);

    return { flowNodes: layoutedNodes, flowEdges: edges };
  }, [workflowState, highlightedNodes, nodeStates, executionProgress.currentNode, isHistoryMode, currentExecutionDetail]);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // 同步更新
  useEffect(() => {
    if (flowNodes.length > 0) {
      setNodes(flowNodes);
      setEdges(flowEdges);
    }
  }, [flowNodes, flowEdges, setNodes, setEdges]);

  // 节点点击
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node.id);
  }, []);

  // 获取选中节点的详情
  const selectedNodeData = useMemo(() => {
    if (!selectedNode || !workflowState) return null;
    const node = workflowState.nodes?.find(n => n.nodeId === selectedNode);
    const agent = workflowState.agents?.find(a => a.agentId === node?.agentId);
    const state = nodeStates[selectedNode];

    // 获取完整的 AgentDefinition（如果有）- 尝试多种 key 匹配
    let agentDefinition = undefined;
    if (workflowState.agentDefinitions) {
      // 尝试多种 key 匹配，增加成功率
      agentDefinition =
        workflowState.agentDefinitions[node?.name || ''] ||
        workflowState.agentDefinitions[node?.agentId || ''] ||
        workflowState.agentDefinitions[node?.displayName || ''];
    }

    return { node, agent, state, agentDefinition };
  }, [selectedNode, workflowState, nodeStates]);

  // 获取选中节点的执行结果（历史模式下）
  const selectedNodeExecutionResult = useMemo(() => {
    if (!isHistoryMode || !currentExecutionDetail || !selectedNode || !workflowState) return undefined;

    const nodeResults = currentExecutionDetail.nodeResults as Record<string, NodeExecutionResult> | undefined;
    if (!nodeResults) return undefined;

    // 通过 workflowNodeId 查找
    const node = workflowState.nodes?.find(n => n.nodeId === selectedNode);
    if (node?.workflowNodeId) {
      return nodeResults[node.workflowNodeId] as NodeExecutionResult | undefined;
    }
    return undefined;
  }, [isHistoryMode, currentExecutionDetail, selectedNode, workflowState]);

  // 处理字段编辑
  const handleEdit = useCallback((field: string, value: unknown) => {
    if (!selectedNodeData?.agentDefinition) return;
    const agentName = selectedNodeData.agentDefinition.name;
    wsService.updateAgent(agentName, { [field]: value });
  }, [selectedNodeData]);

  // 处理 Prompt 优化
  const handleOptimize = useCallback((field: string, currentValue: string) => {
    if (!selectedNodeData?.agentDefinition) return;
    const agentName = selectedNodeData.agentDefinition.name;
    wsService.optimizePrompt(agentName, field, currentValue);
  }, [selectedNodeData]);

  // 获取可用工具列表和模型列表
  const availableTools = workflowState?.availableTools || [];
  const availableModels = workflowState?.availableModels || [];

  // 空状态 - 极简设计
  if (!workflowState?.nodes?.length) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-50/50">
        <div className="text-center max-w-xs">
          <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-blue-50 to-slate-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
            </svg>
          </div>
          <h3 className="text-sm font-medium text-slate-600 mb-2">工作流画布</h3>
          <p className="text-xs text-slate-400 leading-relaxed">
            在左侧描述您的需求<br />
            工作流将在这里实时呈现
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex bg-slate-50/30">
      {/* ReactFlow 画布 */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
          minZoom={0.3}
          maxZoom={1.2}
          defaultEdgeOptions={{
            type: 'default',
          }}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            color="#e2e8f0"
            gap={24}
            size={1}
          />
          <Controls
            position="bottom-right"
            showInteractive={false}
            className="!bg-white !border !border-slate-200 !rounded-lg !shadow-sm"
          />
        </ReactFlow>

        {/* 执行历史选择器 - 右上角 */}
        <ExecutionSelector className="absolute top-4 right-4 z-10" />
      </div>

      {/* 节点详情面板 */}
      {selectedNode && selectedNodeData && (
        <NodeDetailPanel
          node={selectedNodeData.node}
          agent={selectedNodeData.agent}
          agentDefinition={selectedNodeData.agentDefinition}
          state={selectedNodeData.state}
          availableTools={availableTools}
          availableModels={availableModels}
          onClose={() => setSelectedNode(null)}
          onEdit={handleEdit}
          onOptimize={handleOptimize}
          executionResult={selectedNodeExecutionResult}
          isHistoryMode={isHistoryMode}
        />
      )}
    </div>
  );
}
