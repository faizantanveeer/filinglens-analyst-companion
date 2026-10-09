import { ChatView } from "@/components/chat/chat-view";

export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ChatView sessionId={id} />;
}
