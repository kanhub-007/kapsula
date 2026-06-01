/**
 * Pi extension that bridges to the doc-search MCP server via stdio.
 *
 * Spawns `python -m doc_search.presentation.mcp` as a subprocess, discovers MCP tools,
 * and registers them as pi custom tools.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "typebox";
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";

// ── MCP JSON-RPC types ──────────────────────────────────────────

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

interface McpToolDef {
  name: string;
  description?: string;
  inputSchema: {
    type: "object";
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
}

// ── MCP Client over stdio ──────────────────────────────────────

class McpStdioClient {
  private proc: ChildProcess | null = null;
  private requestId = 0;
  private pending = new Map<number, (res: JsonRpcResponse) => void>();
  private buffer = "";

  async start(cwd: string): Promise<void> {
    this.proc = spawn(".venv/Scripts/python.exe", ["-m", "doc_search.presentation.mcp"], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
    });

    const rl = createInterface({ input: this.proc.stdout! });

    rl.on("line", (line: string) => {
      try {
        const msg = JSON.parse(line) as JsonRpcResponse;
        const resolve = this.pending.get(msg.id);
        if (resolve) {
          this.pending.delete(msg.id);
          resolve(msg);
        }
      } catch {
        // skip non-JSON lines
      }
    });

    this.proc.stderr?.on("data", (d) => {
      // swallow stderr (logging)
    });

    // Send initialize
    await this.request("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "pi-doc-search", version: "1.0.0" },
    });

    // Send initialized notification
    this.send({ jsonrpc: "2.0", method: "notifications/initialized" });
  }

  async listTools(): Promise<McpToolDef[]> {
    const res = await this.request("tools/list", {});
    return (res.result as { tools: McpToolDef[] })?.tools ?? [];
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<string> {
    const res = await this.request("tools/call", { name, arguments: args });
    const content = (res.result as { content?: Array<{ type: string; text?: string }> })?.content;
    if (content && content.length > 0) {
      return content.map((c) => c.text ?? "").join("\n");
    }
    return JSON.stringify(res.result);
  }

  private request(method: string, params: Record<string, unknown>): Promise<JsonRpcResponse> {
    const id = ++this.requestId;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP request timeout: ${method}`));
      }, 300000);

      this.pending.set(id, (res: JsonRpcResponse) => {
        clearTimeout(timeout);
        if (res.error) reject(new Error(res.error.message));
        else resolve(res);
      });

      this.send({ jsonrpc: "2.0", id, method, params });
    });
  }

  private send(msg: Record<string, unknown>): void {
    if (!this.proc?.stdin) return;
    this.proc.stdin.write(JSON.stringify(msg) + "\n");
  }

  stop(): void {
    this.proc?.kill();
  }
}

// ── JSON schema → TypeBox helper ───────────────────────────────

function jsonSchemaToTypeBox(schema: McpToolDef["inputSchema"]) {
  const shape: Record<string, unknown> = {};
  const props = schema.properties ?? {};

  for (const [key, prop] of Object.entries(props)) {
    const desc = prop.description ?? key;
    const typ = prop.type ?? "string";

    if (typ === "string") {
      shape[key] = Type.Optional(Type.String({ description: desc }));
    } else if (typ === "integer" || typ === "number") {
      shape[key] = Type.Optional(Type.Number({ description: desc }));
    } else if (typ === "boolean") {
      shape[key] = Type.Optional(Type.Boolean({ description: desc }));
    } else {
      shape[key] = Type.Optional(Type.String({ description: desc }));
    }
  }

  return Type.Object(shape);
}

// ── Extension entry point ──────────────────────────────────────

export default async function (pi: ExtensionAPI) {
  const cwd = process.cwd();
  const client = new McpStdioClient();

  pi.on("session_start", async (_event, ctx) => {
    try {
      ctx.ui.notify("doc-search: Connecting to MCP server...", "info");
      await client.start(cwd);
      const tools = await client.listTools();
      ctx.ui.notify(`doc-search: Connected, ${tools.length} tools discovered`, "success");

      for (const tool of tools) {
        const paramsSchema = jsonSchemaToTypeBox(tool.inputSchema);

        pi.registerTool({
          name: tool.name,
          label: tool.name,
          description: tool.description ?? `doc-search tool: ${tool.name}`,
          parameters: paramsSchema,
          async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
            try {
              const result = await client.callTool(tool.name, params as Record<string, unknown>);
              return {
                content: [{ type: "text" as const, text: result }],
                details: {},
              };
            } catch (err) {
              return {
                content: [
                  {
                    type: "text" as const,
                    text: `doc-search error: ${err instanceof Error ? err.message : String(err)}`,
                  },
                ],
                details: {},
              };
            }
          },
        });

        ctx.ui.notify(`doc-search: Registered tool '${tool.name}'`, "info");
      }
    } catch (err) {
      ctx.ui.notify(
        `doc-search: Failed — ${err instanceof Error ? err.message : String(err)}`,
        "error"
      );
    }
  });

  pi.on("session_shutdown", async () => {
    client.stop();
  });
}
