import { useEffect, useRef, useState } from "react";
import type { AskUserPending, ChatMessage } from "@/api/types";
import { useRespondToAskUser } from "@/hooks/mutations/use-ask-user";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { MessageSquare, Send } from "lucide-react";

export default function ChatPanel({
  runId,
  pendingAskUser,
  initialMessages,
}: {
  runId: string;
  pendingAskUser: AskUserPending | null;
  initialMessages?: ChatMessage[];
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const respond = useRespondToAskUser(runId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastPendingIdRef = useRef<string | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Seed from persisted history when it arrives
  useEffect(() => {
    if (!initialMessages || initialMessages.length === 0) return;
    setMessages((prev) => {
      // Merge persisted history with any messages already in state
      const existingIds = new Set(prev.map((m) => m.id));
      const fromHistory = initialMessages.filter((m) => !existingIds.has(m.id));
      if (fromHistory.length === 0) return prev;
      const merged = [...fromHistory, ...prev];
      merged.sort((a, b) => a.timestamp - b.timestamp);
      for (const m of merged) seenIdsRef.current.add(m.id);
      return merged;
    });
  }, [initialMessages]);

  // When a new pending question arrives, add it to the chat
  useEffect(() => {
    if (!pendingAskUser) return;
    if (lastPendingIdRef.current === pendingAskUser.request_id) return;
    lastPendingIdRef.current = pendingAskUser.request_id;

    // Skip if already loaded from history
    if (seenIdsRef.current.has(pendingAskUser.request_id)) return;
    seenIdsRef.current.add(pendingAskUser.request_id);

    setMessages((prev) => [
      ...prev,
      {
        id: pendingAskUser.request_id,
        role: "agent",
        text: pendingAskUser.question,
        timestamp: pendingAskUser.timestamp,
      },
    ]);
  }, [pendingAskUser]);

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (text: string) => {
    if (!text.trim() || !pendingAskUser) return;

    const msgId = `user-${pendingAskUser.request_id}`;
    // Skip if already in history
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

    try {
      await respond.mutateAsync({
        request_id: pendingAskUser.request_id,
        text: text.trim(),
      });
    } catch {
      // Error state handled by mutation
    }
  };

  const handleChoiceClick = (choice: string) => {
    handleSend(choice);
  };

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
            {messages.map((msg) => (
              <div
                key={msg.id}
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
                  <p className="whitespace-pre-wrap">{msg.text}</p>
                </div>
              </div>
            ))}
            <div ref={scrollRef} />
          </div>
        </ScrollArea>

        {/* Pending indicator + choice buttons */}
        {pendingAskUser && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className="border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-400"
              >
                <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                Waiting for response
              </Badge>
            </div>
            {pendingAskUser.choices &&
              pendingAskUser.choices.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {pendingAskUser.choices.map((choice) => (
                    <Button
                      key={choice}
                      variant="outline"
                      size="sm"
                      onClick={() => handleChoiceClick(choice)}
                      disabled={respond.isPending}
                    >
                      {choice}
                    </Button>
                  ))}
                </div>
              )}
          </div>
        )}

        {/* Input */}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            handleSend(input);
          }}
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              pendingAskUser
                ? "Type your response..."
                : "Waiting for agent question..."
            }
            disabled={!pendingAskUser || respond.isPending}
          />
          <Button
            type="submit"
            size="icon"
            disabled={!pendingAskUser || !input.trim() || respond.isPending}
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
