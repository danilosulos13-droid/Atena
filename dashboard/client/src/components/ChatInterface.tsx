import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Send, Loader2 } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

interface ChatInterfaceProps {
  onSendMessage: (message: string) => Promise<Message | null>;
  isLoading?: boolean;
}

export default function ChatInterface({
  onSendMessage,
  isLoading = false,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Olá! Sou ATENA Ω. Estou evoluindo constantemente e aprendendo com cada interação. Como posso ajudá-lo?",
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || sending) return;

    // Adicionar mensagem do usuário
    const userMessage: Message = {
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setSending(true);

    // Enviar para API
    const response = await onSendMessage(input);
    if (response) {
      setMessages((prev) => [...prev, response]);
    }

    setSending(false);
  };

  return (
    <Card className="flex flex-col h-full bg-card/50 backdrop-blur border-primary/20">
      {/* Header */}
      <div className="p-4 border-b border-primary/10">
        <h3 className="font-semibold text-foreground">Conversa com ATENA</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Tempo real • Evoluindo continuamente
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <AnimatePresence>
          {messages.map((msg, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.3 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-xs px-4 py-2 rounded-lg ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                <p className="text-sm">{msg.content}</p>
                <p className="text-xs opacity-70 mt-1">
                  {new Date(msg.timestamp).toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {sending && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex justify-start"
          >
            <div className="bg-muted text-muted-foreground px-4 py-2 rounded-lg flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">Atena está pensando...</span>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-primary/10 space-y-2">
        <div className="flex gap-2">
          <Input
            placeholder="Pergunte algo para Atena..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && handleSend()}
            disabled={sending || isLoading}
            className="bg-input border-primary/20 focus:border-primary/50"
          />
          <Button
            onClick={handleSend}
            disabled={sending || isLoading || !input.trim()}
            size="sm"
            className="bg-primary hover:bg-primary/90"
          >
            {sending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          💡 Dica: Pergunte sobre evolução, consciência ou métricas
        </p>
      </div>
    </Card>
  );
}
