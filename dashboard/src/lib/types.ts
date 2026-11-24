export type UserRole = "owner" | "admin" | "agent";
export type DocumentStatus = "pending" | "processing" | "ready" | "failed";
export type ConversationMode = "bot" | "human";
export type MessageRole = "customer" | "bot" | "agent";

export interface AuthTokenResponse {
  access_token: string | null;
  token_type: string;
  user_id: string;
  tenant_id: string;
  email: string;
  role: UserRole;
  shop_name: string;
  trial_ends_at: string | null;
}

export interface MeResponse {
  user_id: string;
  tenant_id: string;
  email: string;
  role: UserRole;
  is_super_admin: boolean;
  shop_name: string;
  plan: string;
  status: string;
  trial_ends_at: string | null;
  trial_days_remaining: number;
  used_messages: number;
  limit_messages: number;
  max_channels: number;
  max_documents: number;
  unread_notifications: number;
}

export interface DocumentItem {
  id: string;
  filename: string;
  mime: string;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
  uploaded_at: string;
}

export interface ChannelItem {
  id: string;
  type: "line" | "facebook" | "instagram" | "web";
  name: string;
  active: boolean;
  webhook_url: string;
  created_at: string;
}

export interface ChannelTestResponse {
  ok: boolean;
  bot_name: string | null;
  basic_id: string | null;
  error: string | null;
}

export interface BotSettings {
  shop_name: string;
  tone: string;
  greeting: string;
  handoff_keywords: string[];
  extra_instructions: string;
  fallback_message: string;
  show_citations_to_customer: boolean;
  handoff_notify_channel_id: string | null;
  handoff_notify_target_id: string | null;
  auto_return_hours: number;
}

export interface PlaygroundSource {
  document_id: string;
  filename: string;
  page: number;
}

export interface PlaygroundAskResponse {
  answer: string;
  sources: PlaygroundSource[];
  handoff: boolean;
  handoff_reason: string | null;
  model: string;
  input_tokens: number;
  output_tokens: number;
}

export interface ConversationSummary {
  id: string;
  channel_id: string;
  channel_name: string;
  channel_type: string;
  external_user_id: string;
  customer_name: string | null;
  mode: ConversationMode;
  last_message_preview: string | null;
  last_message_at: string;
  last_agent_reply_at: string | null;
}

export interface MessageItem {
  id: string;
  role: MessageRole;
  content: string;
  sources: Array<{ document_id?: string; filename?: string; page?: number }>;
  created_at: string;
}

export interface ConversationMessagesResponse {
  conversation_id: string;
  customer_name: string | null;
  external_user_id: string;
  mode: ConversationMode;
  items: MessageItem[];
}

export interface DailyMessageCount {
  date: string;
  customer_messages: number;
  bot_messages: number;
  agent_messages: number;
}

export interface TopUnansweredQuestion {
  question: string;
  count: number;
}

export interface AnalyticsSummary {
  days: number;
  total_conversations: number;
  total_customer_messages: number;
  total_bot_messages: number;
  total_handoffs: number;
  auto_resolved_rate: number;
  handoff_rate: number;
  used_messages_this_month: number;
  limit_messages_this_month: number;
  messages_per_day: DailyMessageCount[];
  top_unanswered_questions: TopUnansweredQuestion[];
}

export interface TeamMember {
  id: string;
  email: string;
  role: UserRole;
  created_at: string;
}
