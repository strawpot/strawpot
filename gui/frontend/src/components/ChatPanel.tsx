import { useEffect, useRef, useState } from "react";
import type { AskUserPending, ChatMessage } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import MarkdownContent from "@/components/MarkdownContent";
import CollapsibleMessage from "@/components/CollapsibleMessage";
import { MessageSquare, Send } from "lucide-react";

export default function ChatPanel({
  pendingAskUsers,
  initialMessages,
  respond,
}: {
  pendingAskUsers: AskUserPending[];
  initialMessages?: ChatMessage[];
  respond: (requestId: string, text: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const respondedIdsRef = useRef<Set<string>>(new Set());

  // Seed from persisted history when it arrives
  useEffect(() => {
    if (!initialMessages || initialMessages.length === 0) return;
    setMessages((prev) => {
      const existingIds = new Set(prev.map((m) => m.id));
      const fromHistory = initialMessages.filter((m) => !existingIds.has(m.id));
      if (fromHistory.length === 0) return prev;
      const merged = [...fromHistory, ...prev];
      merged.sort((a, b) => a.timestamp - b.timestamp);
      for (const m of merged) seenIdsRef.current.add(m.id);
      return merged;
    });
  }, [initialMessages]);

  // When new pending questions arrive, add them to the chat
  useEffect(() => {
    if (pendingAskUsers.length === 0) return;

    const newMessages: ChatMessage[] = [];
    for (const pending of pendingAskUsers) {
      if (seenIdsRef.current.has(pending.request_id)) continue;
      seenIdsRef.current.add(pending.request_id);
      newMessages.push({
        id: pending.request_id,
        role: "agent",
        text: pending.question,
        timestamp: pending.timestamp,
      });
    }

    if (newMessages.length > 0) {
      setMessages((prev) => [...prev, ...newMessages]);
    }
  }, [pendingAskUsers]);

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = (text: string, target: AskUserPending) => {
    if (!text.trim()) return;
    if (respondedIdsRef.current.has(target.request_id)) return;
    respondedIdsRef.current.add(target.request_id);

    const msgId = `user-${target.request_id}`;
    if (!seenIdsRef.current.has(msgId)) {
      seenIdsRef.current.add(msgId);
      setMessages((prev) => [
        ...prev,
        {
          id: msgId,
          role: "user",
          text: text.trim(),
          timestamp: Date.now() / 1000,
        },
      ]);
    }
    setInput("");
    respond(target.request_id, text.trim());
  };

  const activePending = pendingAskUsers.length > 0 ? pendingAskUsers[0] : null;

  return (
    <Card className="flex h-[500px] flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
        {/* Messages area */}
        <ScrollArea className="flex-1">
          <div className="space-y-3 pr-3">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
                <MessageSquare className="h-8 w-8" />
                <p className="text-sm">
                  Waiting for the agent to ask a question...
                </p>
              </div>
            )}
            {messages.map((msg) => {
              const pending =
                msg.role === "agent"
                  ? pendingAskUsers.find((p) => p.request_id === msg.id)
                  : undefined;
              return (
                <div key={msg.id}>
                  <div
                    className={cn(
                      "flex",
                      msg.role === "user" ? "justify-end" : "justify-start",
                    )}
                  >
                    <div
                      className={cn(
                        "max-w-[80%] rounded-lg px-3 py-2 text-sm",
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted",
                      )}
                    >
                      <CollapsibleMessage
                        gradientColor={
                          msg.role === "user"
                            ? "var(--color-primary)"
                            : "var(--color-muted)"
                        }
                      >
                        <MarkdownContent content={msg.text} className="whitespace-pre-wrap" />
                      </CollapsibleMessage>
                    </div>
                  </div>
                  {/* Inline choice buttons for pending questions */}
                  {pending?.choices && pending.choices.length > 0 && (
                    <div className="ml-3 mt-1 flex flex-wrap gap-1.5">
                      {pending.choices.map((choice) => (
                        <Button
                          key={choice}
                          variant="outline"
                          size="sm"
                          onClick={() => handleSend(choice, pending)}
                        >
                          {choice}
                        </Button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <div ref={scrollRef} />
          </div>
        </ScrollArea>

        {/* Pending indicator */}
        {pendingAskUsers.length > 0 && (
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className="border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-400"
            >
              <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
              {pendingAskUsers.length === 1
                ? "Waiting for response"
                : `${pendingAskUsers.length} questions waiting`}
            </Badge>
          </div>
        )}

        {/* Input */}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (activePending) handleSend(input, activePending);
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              activePending
                ? "Type your response..."
                : "Waiting for agent question..."
            }
            disabled={!activePending}
          />
          <Button
            type="submit"
            size="icon"
            disabled={!activePending || !input.trim()}
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
