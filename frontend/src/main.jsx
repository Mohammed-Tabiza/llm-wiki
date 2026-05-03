import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8010";

function groupPages(pages) {
  return pages.reduce((groups, page) => {
    groups[page.kind] ??= [];
    groups[page.kind].push(page);
    return groups;
  }, {});
}

function renderInlineMarkdown(text) {
  const parts = [];
  const pattern = /\[([^\]]+)\]\(([^)]+)\)|\[\[([^\]]+)\]\]/g;
  let lastIndex = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (match[1] && match[2]) {
      parts.push(
        <a key={`${match.index}-${match[1]}`} href={match[2]}>
          {match[1]}
        </a>,
      );
    } else if (match[3]) {
      parts.push(
        <span className="wiki-pill" key={`${match.index}-${match[3]}`}>
          {match[3]}
        </span>,
      );
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

function MarkdownView({ content }) {
  if (!content) {
    return <p className="muted">No content selected.</p>;
  }

  return (
    <div className="markdown-view">
      {content.split("\n").map((line, index) => {
        if (line.startsWith("# ")) {
          return <h2 key={index}>{line.slice(2)}</h2>;
        }
        if (line.startsWith("## ")) {
          return <h3 key={index}>{line.slice(3)}</h3>;
        }
        if (line.startsWith("- ")) {
          return <p className="list-line" key={index}>{renderInlineMarkdown(line.slice(2))}</p>;
        }
        if (!line.trim()) {
          return <div className="line-space" key={index} />;
        }
        return <p key={index}>{renderInlineMarkdown(line)}</p>;
      })}
    </div>
  );
}

function App() {
  const [health, setHealth] = useState(null);
  const [pages, setPages] = useState([]);
  const [selectedPage, setSelectedPage] = useState(null);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Ask a question about your generated Obsidian wiki.",
    },
  ]);
  const [question, setQuestion] = useState("");
  const [threadId, setThreadId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [error, setError] = useState("");

  const groupedPages = useMemo(() => groupPages(pages), [pages]);

  useEffect(() => {
    async function loadInitialData() {
      try {
        const [healthResponse, pagesResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/health`),
          fetch(`${API_BASE_URL}/api/pages`),
        ]);

        if (!healthResponse.ok || !pagesResponse.ok) {
          throw new Error("The backend is not responding correctly.");
        }

        setHealth(await healthResponse.json());
        const pagesData = await pagesResponse.json();
        setPages(pagesData.pages);
      } catch (requestError) {
        setError(requestError.message);
      }
    }

    loadInitialData();
  }, []);

  async function loadPage(path) {
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/page/${path}`);
      if (!response.ok) {
        throw new Error("Unable to load wiki page.");
      }
      setSelectedPage(await response.json());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function askQuestion(event) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || isLoading) {
      return;
    }

    setQuestion("");
    setError("");
    setIsLoading(true);
    setStatusText("Searching wiki");
    setMessages((current) => [
      ...current,
      { role: "user", content: trimmedQuestion },
      { role: "assistant", content: "" },
    ]);

    try {
      const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmedQuestion, thread_id: threadId }),
      });

      if (!response.ok) {
        throw new Error("The wiki agent could not answer this question.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.trim()) {
            continue;
          }

          const event = JSON.parse(line);

          if (event.type === "thread") {
            setThreadId(event.thread_id);
          }

          if (event.type === "status") {
            setStatusText(event.message);
          }

          if (event.type === "token") {
            setStatusText("Answering");
            setMessages((current) => {
              const next = [...current];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: `${last.content}${event.content}` };
              return next;
            });
          }
        }
      }
    } catch (requestError) {
      setError(requestError.message);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: "I could not reach the wiki agent." },
      ]);
    } finally {
      setIsLoading(false);
      setStatusText("");
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">LW</div>
          <div>
            <h1>LLM Wiki</h1>
            <p>{health?.index_exists ? "Index ready" : "Index missing"}</p>
          </div>
        </div>

        <section className="page-list">
          {Object.entries(groupedPages).map(([kind, group]) => (
            <div className="page-group" key={kind}>
              <h2>{kind}</h2>
              {group.map((page) => (
                <button
                  className={selectedPage?.path === page.path ? "page-button active" : "page-button"}
                  key={page.path}
                  onClick={() => loadPage(page.path)}
                  type="button"
                >
                  <span>{page.title}</span>
                  <small>{page.path}</small>
                </button>
              ))}
            </div>
          ))}
        </section>
      </aside>

      <section className="chat-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">Local agent</p>
            <h2>Ask your generated wiki</h2>
          </div>
          <span className="model-badge">{health?.model ?? "checking model"}</span>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        <div className="messages">
          {messages.map((message, index) => (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              {message.content ? (
                <MarkdownView content={message.content} />
              ) : (
                <p className="muted">{statusText || "Preparing answer"}</p>
              )}
            </article>
          ))}
        </div>

        <form className="composer" onSubmit={askQuestion}>
          <input
            aria-label="Ask a question"
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Quel est le rôle de LangGraph ?"
            type="text"
            value={question}
          />
          <button disabled={isLoading || !question.trim()} type="submit">
            Send
          </button>
        </form>
      </section>

      <section className="reader-panel">
        <header>
          <p className="eyebrow">Wiki page</p>
          <h2>{selectedPage?.title ?? "Select a page"}</h2>
          {selectedPage ? <a href={selectedPage.obsidian_url}>Open in Obsidian</a> : null}
        </header>
        <MarkdownView content={selectedPage?.content} />
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
