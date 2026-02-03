# Web UI 与 WebSocket 通信协议

## 1. 概述

Web UI 提供了一个可视化的界面，用于对话式工作流构建和执行监控。

### 1.1 设计目标

| 目标 | 描述 |
|------|------|
| **对话式交互** | 通过自然语言对话构建工作流 |
| **实时可视化** | 实时显示工作流结构和执行状态 |
| **配置编辑** | 在线编辑 Agent 配置和 Prompt |
| **执行监控** | 监控执行进度和结果 |
| **历史管理** | 查看执行历史和检查点 |

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| **前端框架** | React + TypeScript |
| **状态管理** | Zustand |
| **工作流可视化** | ReactFlow |
| **样式** | TailwindCSS |
| **通信** | WebSocket |
| **后端框架** | FastAPI |

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Web UI 架构                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        前端 (React)                              │   │
│  │                                                                  │   │
│  │  ┌────────────────────────────────────────────────────────────┐ │   │
│  │  │                     App.tsx                                 │ │   │
│  │  │  ┌───────────────┐              ┌───────────────────────┐  │ │   │
│  │  │  │ ChatPanel     │◄────────────►│ WorkflowCanvas        │  │ │   │
│  │  │  │ 对话面板       │              │ 工作流画布             │  │ │   │
│  │  │  └───────────────┘              └───────────────────────┘  │ │   │
│  │  └────────────────────────────────────────────────────────────┘ │   │
│  │                              │                                    │   │
│  │                              ▼                                    │   │
│  │  ┌────────────────────────────────────────────────────────────┐ │   │
│  │  │                     状态管理                                 │ │   │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐│ │   │
│  │  │  │ appStore    │  │ useWebSocket│  │ websocket.ts        ││ │   │
│  │  │  │ (Zustand)   │  │ (Hook)      │  │ (Service)           ││ │   │
│  │  │  └─────────────┘  └─────────────┘  └─────────────────────┘│ │   │
│  │  └────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │ WebSocket                                │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        后端 (FastAPI)                            │   │
│  │                                                                  │   │
│  │  ┌────────────────────────────────────────────────────────────┐ │   │
│  │  │                     WebSocket 层                            │ │   │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐│ │   │
│  │  │  │ handlers.py │  │ manager.py  │  │ SessionManager      ││ │   │
│  │  │  │ 消息处理     │  │ 连接管理    │  │ 会话管理            ││ │   │
│  │  │  └─────────────┘  └─────────────┘  └─────────────────────┘│ │   │
│  │  └────────────────────────────────────────────────────────────┘ │   │
│  │                              │                                    │   │
│  │                              ▼                                    │   │
│  │  ┌────────────────────────────────────────────────────────────┐ │   │
│  │  │              ConversationalWorkflowBuilder                  │ │   │
│  │  └────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 前端组件

### 3.1 App.tsx - 应用入口

```typescript
// web-ui/src/App.tsx

import { useState, useEffect } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { useWebSocket } from './hooks/useWebSocket';

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [panelWidth, setPanelWidth] = useState(675);
  
  const { isConnected, sendMessage, sendAction } = useWebSocket(sessionId);
  
  useEffect(() => {
    // 从 localStorage 恢复或创建新会话
    const savedSessionId = localStorage.getItem('sessionId');
    if (savedSessionId) {
      setSessionId(savedSessionId);
    } else {
      const newSessionId = `session_${Date.now()}`;
      localStorage.setItem('sessionId', newSessionId);
      setSessionId(newSessionId);
    }
  }, []);
  
  return (
    <div className="h-screen flex flex-col">
      {/* 头部状态栏 */}
      <header className="h-12 bg-gray-800 text-white flex items-center px-4">
        <span className={`w-2 h-2 rounded-full mr-2 ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
        <span>{isConnected ? '已连接' : '连接中...'}</span>
        <span className="ml-4 text-gray-400">会话: {sessionId}</span>
      </header>
      
      {/* 主内容区 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧对话面板 */}
        <div style={{ width: panelWidth }} className="border-r">
          <ChatPanel 
            sendMessage={sendMessage}
            sendAction={sendAction}
          />
        </div>
        
        {/* 可拖拽分隔条 */}
        <ResizeHandle onResize={setPanelWidth} />
        
        {/* 右侧工作流画布 */}
        <div className="flex-1">
          <WorkflowCanvas />
        </div>
      </div>
    </div>
  );
}
```

### 3.2 ChatPanel - 对话面板

```typescript
// web-ui/src/components/ChatPanel/index.tsx

import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../../stores/appStore';
import { MessageBubble } from './MessageBubble';
import { QuickActions } from './QuickActions';
import { CheckpointList } from './CheckpointList';

interface ChatPanelProps {
  sendMessage: (content: string) => void;
  sendAction: (action: string, params?: object) => void;
}

export function ChatPanel({ sendMessage, sendAction }: ChatPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  const { messages, suggestedActions, isLoading, workflowState } = useAppStore();
  
  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    sendMessage(input);
    setInput('');
  };
  
  // 智能滚动：仅在用户接近底部时自动滚动
  useEffect(() => {
    if (messagesEndRef.current) {
      const container = messagesEndRef.current.parentElement;
      if (container) {
        const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
        if (isNearBottom) {
          messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
      }
    }
  }, [messages]);
  
  return (
    <div className="h-full flex flex-col">
      {/* 检查点列表 */}
      {workflowState.checkpoints.length > 0 && (
        <CheckpointList 
          checkpoints={workflowState.checkpoints}
          onRollback={(id) => sendAction('rollback', { checkpoint_id: id })}
        />
      )}
      
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <MessageBubble key={message.id || index} message={message} />
        ))}
        <div ref={messagesEndRef} />
      </div>
      
      {/* 建议操作 */}
      {suggestedActions.length > 0 && (
        <QuickActions 
          actions={suggestedActions}
          onAction={(action) => sendAction(action)}
        />
      )}
      
      {/* 输入框 */}
      <div className="border-t p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="描述您想要构建的工作流..."
            className="flex-1 px-4 py-2 border rounded-lg"
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="px-6 py-2 bg-blue-500 text-white rounded-lg disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
```

### 3.3 WorkflowCanvas - 工作流画布

```typescript
// web-ui/src/components/WorkflowCanvas/index.tsx

import { useMemo, useCallback } from 'react';
import ReactFlow, { 
  Node, 
  Edge, 
  Controls, 
  Background,
  useNodesState,
  useEdgesState,
} from 'reactflow';
import { useAppStore } from '../../stores/appStore';
import { AgentNode } from './AgentNode';
import { NodeDetailPanel } from './NodeDetailPanel';

const nodeTypes = {
  agent: AgentNode,
};

export function WorkflowCanvas() {
  const { workflowState, nodeStates, selectedNode, setSelectedNode } = useAppStore();
  
  // 将工作流状态转换为 ReactFlow 格式
  const { flowNodes, flowEdges } = useMemo(() => {
    return convertToReactFlow(workflowState, nodeStates);
  }, [workflowState, nodeStates]);
  
  const [nodes, setNodes, onNodesChange] = useNodesState(flowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);
  
  // 节点点击处理
  const onNodeClick = useCallback((event: React.MouseEvent, node: Node) => {
    setSelectedNode(node.id);
  }, [setSelectedNode]);
  
  return (
    <div className="h-full flex">
      {/* ReactFlow 画布 */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
        >
          <Controls />
          <Background />
        </ReactFlow>
      </div>
      
      {/* 节点详情面板 */}
      {selectedNode && (
        <NodeDetailPanel 
          nodeId={selectedNode}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  );
}

function convertToReactFlow(
  workflowState: WorkflowState,
  nodeStates: Record<string, NodeState>,
) {
  // DAG 自动布局算法
  const layers = topologicalSort(workflowState.nodes, workflowState.edges);
  
  const flowNodes: Node[] = workflowState.nodes.map((node, index) => {
    const layer = layers.get(node.node_id) || 0;
    const state = nodeStates[node.node_id];
    
    return {
      id: node.node_id,
      type: node.node_type === 'agent' ? 'agent' : 'default',
      position: { x: layer * 250, y: index * 100 },
      data: {
        label: node.name,
        status: state?.status || 'pending',
        duration: state?.duration,
        tools: node.tools,
      },
    };
  });
  
  const flowEdges: Edge[] = workflowState.edges.map((edge, index) => ({
    id: `e${index}`,
    source: edge.from_node,
    target: edge.to_node,
    animated: nodeStates[edge.from_node]?.status === 'running',
  }));
  
  return { flowNodes, flowEdges };
}
```

### 3.4 NodeDetailPanel - 节点详情面板

```typescript
// web-ui/src/components/WorkflowCanvas/NodeDetailPanel.tsx

import { useState, useEffect } from 'react';
import { useAppStore } from '../../stores/appStore';
import { useWebSocket } from '../../hooks/useWebSocket';

interface NodeDetailPanelProps {
  nodeId: string;
  onClose: () => void;
}

export function NodeDetailPanel({ nodeId, onClose }: NodeDetailPanelProps) {
  const { workflowState, nodeStates, selectedExecutionId } = useAppStore();
  const { sendAction } = useWebSocket();
  
  const [activeTab, setActiveTab] = useState<'config' | 'result'>('config');
  const [pendingChanges, setPendingChanges] = useState<Record<string, any>>({});
  
  // 获取节点和 Agent 信息
  const node = workflowState.nodes.find(n => n.node_id === nodeId);
  const agent = workflowState.agents.find(a => a.name === node?.agent_id);
  const nodeState = nodeStates[nodeId];
  
  // 保存更改
  const handleSave = async () => {
    if (Object.keys(pendingChanges).length === 0) return;
    
    sendAction('UPDATE_AGENT', {
      agent_name: agent?.name,
      updates: pendingChanges,
    });
    
    setPendingChanges({});
  };
  
  // Prompt 优化
  const handleOptimize = async (field: string, currentValue: string) => {
    sendAction('OPTIMIZE_PROMPT', {
      agent_name: agent?.name,
      field,
      current_value: currentValue,
    });
  };
  
  return (
    <div className="w-96 border-l bg-white overflow-y-auto">
      {/* 头部 */}
      <div className="p-4 border-b flex justify-between items-center">
        <h3 className="font-semibold">{node?.name}</h3>
        <button onClick={onClose} className="text-gray-500">✕</button>
      </div>
      
      {/* Tab 切换 */}
      <div className="flex border-b">
        <button
          className={`flex-1 py-2 ${activeTab === 'config' ? 'border-b-2 border-blue-500' : ''}`}
          onClick={() => setActiveTab('config')}
        >
          配置
        </button>
        <button
          className={`flex-1 py-2 ${activeTab === 'result' ? 'border-b-2 border-blue-500' : ''}`}
          onClick={() => setActiveTab('result')}
          disabled={!nodeState?.result}
        >
          执行结果
        </button>
      </div>
      
      {/* 配置面板 */}
      {activeTab === 'config' && agent && (
        <div className="p-4 space-y-4">
          {/* 背景指令 */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-sm font-medium">背景指令</label>
              <button
                onClick={() => handleOptimize('background_instruction', agent.background_instruction.role_description)}
                className="text-xs text-blue-500"
              >
                AI 优化
              </button>
            </div>
            <textarea
              value={pendingChanges.role_description ?? agent.background_instruction.role_description}
              onChange={(e) => setPendingChanges({
                ...pendingChanges,
                role_description: e.target.value,
              })}
              className="w-full h-24 p-2 border rounded text-sm"
            />
          </div>
          
          {/* 模型配置 */}
          <div>
            <label className="text-sm font-medium">模型</label>
            <select
              value={pendingChanges.model_name ?? agent.model_config.model_name}
              onChange={(e) => setPendingChanges({
                ...pendingChanges,
                model_name: e.target.value,
              })}
              className="w-full p-2 border rounded"
            >
              <option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
              <option value="claude-3-haiku">Claude Haiku</option>
              <option value="deepseek/deepseek-v3">DeepSeek V3</option>
            </select>
          </div>
          
          {/* 工具列表 */}
          <div>
            <label className="text-sm font-medium">工具</label>
            <div className="mt-1 space-y-1">
              {agent.tool_references?.map((tool) => (
                <div key={tool.tool_id} className="flex items-center">
                  <input
                    type="checkbox"
                    checked={tool.enabled}
                    onChange={(e) => {
                      // 更新工具启用状态
                    }}
                    className="mr-2"
                  />
                  <span className="text-sm">@{tool.alias}</span>
                </div>
              ))}
            </div>
          </div>
          
          {/* 保存按钮 */}
          {Object.keys(pendingChanges).length > 0 && (
            <button
              onClick={handleSave}
              className="w-full py-2 bg-blue-500 text-white rounded"
            >
              保存更改
            </button>
          )}
        </div>
      )}
      
      {/* 执行结果面板 */}
      {activeTab === 'result' && nodeState?.result && (
        <div className="p-4">
          <div className="mb-2 flex justify-between text-sm text-gray-500">
            <span>状态: {nodeState.status}</span>
            <span>耗时: {nodeState.duration}ms</span>
          </div>
          <pre className="bg-gray-100 p-2 rounded text-xs overflow-auto max-h-96">
            {JSON.stringify(nodeState.result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
```

---

## 4. 状态管理

### 4.1 appStore - Zustand Store

```typescript
// web-ui/src/stores/appStore.ts

import { create } from 'zustand';
import { Message, WorkflowState, NodeState, ExecutionRecord } from '../types';

interface AppState {
  // 会话
  sessionId: string | null;
  setSessionId: (id: string) => void;
  
  // 消息
  messages: Message[];
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  
  // 工作流状态
  workflowState: WorkflowState;
  setWorkflowState: (state: WorkflowState) => void;
  
  // 节点状态
  nodeStates: Record<string, NodeState>;
  setNodeState: (nodeId: string, state: NodeState) => void;
  
  // 执行历史
  executionHistory: ExecutionRecord[];
  selectedExecutionId: string | null;
  setExecutionHistory: (history: ExecutionRecord[]) => void;
  selectExecution: (id: string | null) => void;
  
  // UI 状态
  isLoading: boolean;
  setLoading: (loading: boolean) => void;
  selectedNode: string | null;
  setSelectedNode: (nodeId: string | null) => void;
  suggestedActions: string[];
  setSuggestedActions: (actions: string[]) => void;
  highlightedNodes: string[];
  setHighlightedNodes: (nodes: string[]) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // 会话
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),
  
  // 消息（支持去重）
  messages: [],
  addMessage: (message) => set((state) => {
    // 检查是否是进度消息更新
    if (message.isProgress && message.id) {
      const existingIndex = state.messages.findIndex(m => m.id === message.id);
      if (existingIndex >= 0) {
        const newMessages = [...state.messages];
        newMessages[existingIndex] = { ...newMessages[existingIndex], ...message };
        return { messages: newMessages };
      }
    }
    return { messages: [...state.messages, message] };
  }),
  
  updateMessage: (id, updates) => set((state) => ({
    messages: state.messages.map(m => m.id === id ? { ...m, ...updates } : m),
  })),
  
  // 工作流状态
  workflowState: {
    mode: 'idle',
    phase: 'initial',
    agents: [],
    nodes: [],
    edges: [],
    checkpoints: [],
  },
  setWorkflowState: (workflowState) => set({ workflowState }),
  
  // 节点状态
  nodeStates: {},
  setNodeState: (nodeId, state) => set((s) => ({
    nodeStates: { ...s.nodeStates, [nodeId]: state },
  })),
  
  // 执行历史
  executionHistory: [],
  selectedExecutionId: null,
  setExecutionHistory: (history) => set({ executionHistory: history }),
  selectExecution: (id) => set({ selectedExecutionId: id }),
  
  // UI 状态
  isLoading: false,
  setLoading: (isLoading) => set({ isLoading }),
  selectedNode: null,
  setSelectedNode: (selectedNode) => set({ selectedNode }),
  suggestedActions: [],
  setSuggestedActions: (suggestedActions) => set({ suggestedActions }),
  highlightedNodes: [],
  setHighlightedNodes: (highlightedNodes) => set({ highlightedNodes }),
}));
```

---

## 5. WebSocket 通信协议

### 5.1 消息类型

```typescript
// web-ui/src/types/index.ts

export enum WSMessageType {
  // === 连接 ===
  CONNECTED = 'CONNECTED',
  PING = 'PING',
  PONG = 'PONG',
  
  // === 聊天 ===
  CHAT_MESSAGE = 'CHAT_MESSAGE',
  USER_ACTION = 'USER_ACTION',
  
  // === 工作流 ===
  WORKFLOW_UPDATE = 'WORKFLOW_UPDATE',
  NODE_HIGHLIGHT = 'NODE_HIGHLIGHT',
  
  // === 执行 ===
  EXECUTION_EVENT = 'EXECUTION_EVENT',
  PROGRESS_UPDATE = 'PROGRESS_UPDATE',
  CHECKPOINT_CREATED = 'CHECKPOINT_CREATED',
  
  // === Agent ===
  AGENT_GENERATION_PROGRESS = 'AGENT_GENERATION_PROGRESS',
  AGENT_UPDATED = 'AGENT_UPDATED',
  UPDATE_AGENT = 'UPDATE_AGENT',
  OPTIMIZE_PROMPT = 'OPTIMIZE_PROMPT',
  
  // === 历史 ===
  GET_EXECUTION_HISTORY = 'GET_EXECUTION_HISTORY',
  EXECUTION_HISTORY = 'EXECUTION_HISTORY',
  GET_EXECUTION_DETAIL = 'GET_EXECUTION_DETAIL',
  EXECUTION_DETAIL = 'EXECUTION_DETAIL',
  
  // === 建议 ===
  SUGGESTED_ACTIONS = 'SUGGESTED_ACTIONS',
  
  // === 错误 ===
  ERROR = 'ERROR',
}
```

### 5.2 消息格式

```typescript
interface WSMessage {
  type: WSMessageType;
  payload: Record<string, unknown>;
  timestamp: string;
}

// 示例消息

// 聊天消息
{
  type: 'CHAT_MESSAGE',
  payload: {
    role: 'user' | 'assistant' | 'system',
    content: string,
    id?: string,
    isProgress?: boolean,
  },
  timestamp: '2026-02-03T10:00:00Z'
}

// 工作流更新
{
  type: 'WORKFLOW_UPDATE',
  payload: {
    mode: 'planning' | 'executing' | 'completed',
    phase: string,
    agents: AgentInfo[],
    nodes: NodeInfo[],
    edges: EdgeInfo[],
    checkpoints: CheckpointInfo[],
  },
  timestamp: '2026-02-03T10:00:00Z'
}

// 执行事件
{
  type: 'EXECUTION_EVENT',
  payload: {
    event_type: 'node_started' | 'node_completed' | 'node_failed',
    node_id: string,
    data: {
      result?: any,
      error?: string,
      duration_ms?: number,
    },
  },
  timestamp: '2026-02-03T10:00:00Z'
}

// Agent 生成进度
{
  type: 'AGENT_GENERATION_PROGRESS',
  payload: {
    agent_name: string,
    phase: 'analyzing' | 'generating' | 'validating' | 'completed',
    progress: number,  // 0-100
    message: string,
  },
  timestamp: '2026-02-03T10:00:00Z'
}
```

### 5.3 WebSocket 服务

```typescript
// web-ui/src/services/websocket.ts

type MessageHandler = (message: WSMessage) => void;

class WebSocketService {
  private ws: WebSocket | null = null;
  private handlers: Map<WSMessageType, Set<MessageHandler>> = new Map();
  private handlerIds: Map<string, MessageHandler> = new Map();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private pingInterval: NodeJS.Timer | null = null;
  
  connect(sessionId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const url = `ws://${window.location.host}/ws/${sessionId}`;
      this.ws = new WebSocket(url);
      
      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        this.startHeartbeat();
        resolve();
      };
      
      this.ws.onmessage = (event) => {
        const message: WSMessage = JSON.parse(event.data);
        this.dispatch(message);
      };
      
      this.ws.onclose = () => {
        console.log('WebSocket disconnected');
        this.stopHeartbeat();
        this.attemptReconnect(sessionId);
      };
      
      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        reject(error);
      };
    });
  }
  
  send(type: WSMessageType, payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type,
        payload,
        timestamp: new Date().toISOString(),
      }));
    }
  }
  
  on(type: WSMessageType, handler: MessageHandler, handlerId?: string): () => void {
    // 支持处理器去重
    if (handlerId) {
      const existing = this.handlerIds.get(handlerId);
      if (existing) {
        this.handlers.get(type)?.delete(existing);
      }
      this.handlerIds.set(handlerId, handler);
    }
    
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);
    
    // 返回取消订阅函数
    return () => {
      this.handlers.get(type)?.delete(handler);
      if (handlerId) {
        this.handlerIds.delete(handlerId);
      }
    };
  }
  
  private dispatch(message: WSMessage): void {
    const handlers = this.handlers.get(message.type);
    handlers?.forEach(handler => handler(message));
  }
  
  private startHeartbeat(): void {
    this.pingInterval = setInterval(() => {
      this.send(WSMessageType.PING, {});
    }, 30000);
  }
  
  private stopHeartbeat(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }
  
  private attemptReconnect(sessionId: string): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnect attempts reached');
      return;
    }
    
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    
    setTimeout(() => {
      console.log(`Reconnecting... (attempt ${this.reconnectAttempts})`);
      this.connect(sessionId);
    }, delay);
  }
}

export const wsService = new WebSocketService();
```

---

## 6. 后端实现

### 6.1 FastAPI 应用

```python
# src/web/app.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .websocket.handlers import WebSocketHandler
from .websocket.manager import ConnectionManager
from .routers import sessions, workflows, execution

def create_app() -> FastAPI:
    app = FastAPI(title="Agent Framework API")
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 路由
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
    app.include_router(execution.router, prefix="/api/execution", tags=["execution"])
    
    # WebSocket
    connection_manager = ConnectionManager()
    ws_handler = WebSocketHandler(connection_manager)
    
    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        await connection_manager.connect(websocket, session_id)
        try:
            # 发送连接成功消息
            await websocket.send_json({
                "type": "CONNECTED",
                "payload": {"session_id": session_id},
            })
            
            while True:
                data = await websocket.receive_json()
                await ws_handler.handle_message(session_id, data, websocket)
                
        except WebSocketDisconnect:
            connection_manager.disconnect(session_id)
    
    # 静态文件（前端）
    app.mount("/", StaticFiles(directory="web-ui/dist", html=True), name="static")
    
    return app
```

### 6.2 WebSocket 处理器

```python
# src/web/websocket/handlers.py

from typing import Dict, Any
from fastapi import WebSocket

from ...evolution import ConversationalWorkflowBuilder


class WebSocketHandler:
    """WebSocket 消息处理器"""
    
    def __init__(self, connection_manager: "ConnectionManager"):
        self.connection_manager = connection_manager
        self.session_builders: Dict[str, ConversationalWorkflowBuilder] = {}
    
    async def handle_message(
        self,
        session_id: str,
        message: Dict[str, Any],
        websocket: WebSocket,
    ):
        """处理 WebSocket 消息"""
        msg_type = message.get("type")
        payload = message.get("payload", {})
        
        if msg_type == "PING":
            await websocket.send_json({"type": "PONG", "payload": {}})
            
        elif msg_type == "CHAT_MESSAGE":
            await self._handle_chat_message(session_id, payload, websocket)
            
        elif msg_type == "USER_ACTION":
            await self._handle_user_action(session_id, payload, websocket)
            
        elif msg_type == "UPDATE_AGENT":
            await self._handle_update_agent(session_id, payload, websocket)
            
        elif msg_type == "OPTIMIZE_PROMPT":
            await self._handle_optimize_prompt(session_id, payload, websocket)
            
        elif msg_type == "GET_EXECUTION_HISTORY":
            await self._handle_get_execution_history(session_id, websocket)
    
    async def _handle_chat_message(
        self,
        session_id: str,
        payload: Dict[str, Any],
        websocket: WebSocket,
    ):
        """处理聊天消息"""
        builder = self._get_or_create_builder(session_id, websocket)
        
        content = payload.get("content", "")
        
        # 处理消息
        response = await builder.process_message(content)
        
        # 发送响应
        await websocket.send_json({
            "type": "CHAT_MESSAGE",
            "payload": {
                "role": "assistant",
                "content": response.message,
            },
        })
        
        # 发送建议操作
        if response.suggested_actions:
            await websocket.send_json({
                "type": "SUGGESTED_ACTIONS",
                "payload": {"actions": response.suggested_actions},
            })
    
    def _get_or_create_builder(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> ConversationalWorkflowBuilder:
        """获取或创建会话的构建器"""
        if session_id not in self.session_builders:
            # 创建回调
            async def on_workflow_update(plan: Dict):
                await websocket.send_json({
                    "type": "WORKFLOW_UPDATE",
                    "payload": plan,
                })
            
            async def on_execution_event(event: Dict):
                await websocket.send_json({
                    "type": "EXECUTION_EVENT",
                    "payload": event,
                })
            
            async def on_generation_progress(progress: Dict):
                await websocket.send_json({
                    "type": "AGENT_GENERATION_PROGRESS",
                    "payload": progress,
                })
            
            # 创建构建器
            builder = ConversationalWorkflowBuilder(
                dialogue_agent=...,  # 依赖注入
                workflow_tools=...,
                on_workflow_update=on_workflow_update,
                on_execution_event=on_execution_event,
                on_generation_progress=on_generation_progress,
            )
            
            self.session_builders[session_id] = builder
        
        return self.session_builders[session_id]
```

---

## 7. 使用流程

### 7.1 典型交互流程

```
用户                          前端                          后端
 │                            │                             │
 │  描述工作流需求             │                             │
 │ ─────────────────────────► │                             │
 │                            │  CHAT_MESSAGE               │
 │                            │ ─────────────────────────►  │
 │                            │                             │ 处理消息
 │                            │                             │ 调用 DialogueAgent
 │                            │                             │ 生成规划
 │                            │  CHAT_MESSAGE (响应)         │
 │                            │ ◄─────────────────────────  │
 │                            │  WORKFLOW_UPDATE            │
 │                            │ ◄─────────────────────────  │
 │  看到规划可视化             │                             │
 │ ◄───────────────────────── │                             │
 │                            │                             │
 │  "调整一下风险分析"          │                             │
 │ ─────────────────────────► │                             │
 │                            │  CHAT_MESSAGE               │
 │                            │ ─────────────────────────►  │
 │                            │                             │ iterate_plan
 │                            │  WORKFLOW_UPDATE            │
 │                            │ ◄─────────────────────────  │
 │                            │                             │
 │  "批准并执行"               │                             │
 │ ─────────────────────────► │                             │
 │                            │  USER_ACTION (execute)      │
 │                            │ ─────────────────────────►  │
 │                            │                             │ 开始执行
 │                            │  EXECUTION_EVENT (started)  │
 │                            │ ◄─────────────────────────  │
 │                            │  EXECUTION_EVENT (node)     │
 │  看到节点执行状态           │ ◄─────────────────────────  │
 │ ◄───────────────────────── │  ...                        │
 │                            │  EXECUTION_EVENT (done)     │
 │                            │ ◄─────────────────────────  │
 │  看到执行结果               │                             │
 │ ◄───────────────────────── │                             │
```

---

## 8. 配置和部署

### 8.1 开发环境

```bash
# 启动后端
cd agent_framework
uvicorn src.web.app:create_app --factory --reload --port 8000

# 启动前端（开发模式）
cd web-ui
npm run dev
```

### 8.2 生产部署

```bash
# 构建前端
cd web-ui
npm run build

# 启动后端（会自动提供前端静态文件）
uvicorn src.web.app:create_app --factory --host 0.0.0.0 --port 8000
```

### 8.3 环境变量

```bash
# 后端配置
CLAUDE_API_KEY=your_api_key
DATABASE_URL=postgresql://user:pass@localhost/db
REDIS_URL=redis://localhost:6379

# 前端配置
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```
