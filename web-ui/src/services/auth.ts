/**
 * 认证服务
 *
 * 提供用户登录、登出、Token 管理功能。
 */

const TOKEN_KEY = 'qveris_auth_token';
const USER_KEY = 'qveris_auth_user';

export interface AuthUser {
  username: string;
  display_name: string;
  role: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  display_name: string;
  role: string;
}

/**
 * 用户登录
 */
export async function login(username: string, password: string): Promise<AuthUser> {
  const protocol = window.location.protocol;
  const host = window.location.host;
  const url = `${protocol}//${host}/api/auth/login`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || '登录失败');
  }

  const data: LoginResponse = await response.json();

  // 保存 token 和用户信息到 localStorage
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify({
    username: data.username,
    display_name: data.display_name,
    role: data.role,
  }));

  return {
    username: data.username,
    display_name: data.display_name,
    role: data.role,
  };
}

/**
 * 用户登出
 */
export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  // 清除 session 信息，登录后会创建新 session
  localStorage.removeItem('workflow_session_id');
}

/**
 * 获取存储的 JWT token
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * 获取当前已登录的用户信息（从 localStorage 读取）
 */
export function getCurrentUser(): AuthUser | null {
  const userStr = localStorage.getItem(USER_KEY);
  if (!userStr) return null;
  try {
    return JSON.parse(userStr) as AuthUser;
  } catch {
    return null;
  }
}

/**
 * 检查是否已认证（有 token 存在）
 *
 * 注意：这只是客户端检查，不验证 token 是否过期。
 * 过期的 token 会在后端请求时被拒绝，此时前端应跳转到登录页。
 */
export function isAuthenticated(): boolean {
  return !!getToken();
}

/**
 * 验证当前 token 是否仍然有效（调用后端 /api/auth/me）
 */
export async function verifyToken(): Promise<AuthUser | null> {
  const token = getToken();
  if (!token) return null;

  try {
    const protocol = window.location.protocol;
    const host = window.location.host;
    const url = `${protocol}//${host}/api/auth/me`;

    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!response.ok) {
      // Token 无效，清除本地存储
      logout();
      return null;
    }

    const user: AuthUser = await response.json();
    // 更新本地用户信息
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  } catch {
    // 网络错误等情况，保留 token（可能只是暂时无法连接）
    return getCurrentUser();
  }
}
