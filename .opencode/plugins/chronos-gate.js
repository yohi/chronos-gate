const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const gatewayPort = process.env.MCP_GATEWAY_PORT || '9100';


// Debug log helper
function logDebug(msg) {
  const isDebug = !!(process.env.CHRONOS_GATE_DEBUG || process.env.NODE_DEBUG);
  if (!isDebug) return;

  let output = msg;
  if (typeof msg === 'string') {
    output = msg
      .replace(/(sk-[a-zA-Z0-9]{20,})/g, '[REDACTED_API_KEY]')
      .replace(/(bearer\s+)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]')
      .replace(/(authorization:\s*)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]');
  } else if (typeof msg === 'object' && msg !== null) {
    try {
      output = JSON.stringify(msg);
      output = output
        .replace(/(sk-[a-zA-Z0-9]{20,})/g, '[REDACTED_API_KEY]')
        .replace(/(bearer\s+)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]')
        .replace(/(authorization:\s*)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]');
    } catch {
      output = '[Unserializable Object]';
    }
  }

  try {
    const logDir = path.resolve(os.homedir() || process.env.HOME || '', '.config', 'opencode');
    const logPath = path.resolve(logDir, 'chronos-gate-debug.log');
    fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${output}\n`);
  } catch {}
}

// Load global config from ~/.config/opencode/chronos-gate.env
const homeDirectory = os.homedir() || process.env.HOME || '';
const globalEnvPath = path.resolve(homeDirectory, '.config', 'opencode', 'chronos-gate.env');

// Helper to manually parse a .env file and return key-value pairs
function loadEnvFile(envPath) {
  try {
    if (!fs.existsSync(envPath)) return {};
    const content = fs.readFileSync(envPath, 'utf-8');
    const env = {};
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const match = trimmed.match(/^([^=]+)=(.*)$/);
      if (match) {
        const key = match[1].trim();
        let val = match[2].trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.substring(1, val.length - 1);
        } else {
          const commentIndex = val.indexOf('#');
          if (commentIndex !== -1) {
            val = val.substring(0, commentIndex).trim();
          }
        }
        env[key] = val;
      }
    }
    return env;
  } catch (e) {
    logDebug(`Failed to parse .env at ${envPath}: ${e.message}`);
    return {};
  }
}

if (fs.existsSync(globalEnvPath)) {
  const globalEnv = loadEnvFile(globalEnvPath);
  logDebug(`Loaded global config from ${globalEnvPath}`);
  for (const [k, v] of Object.entries(globalEnv)) {
    if (process.env[k] === undefined) {
      process.env[k] = v;
    }
  }
}

logDebug("Plugin script loaded (evaluated).");


// Helper to get prioritized list of directories to look for .env
function getChronosSearchDirs(directory = null) {
  const searchDirs = [];

  if (process.env.CHRONOS_REPO_PATH) {
    const explicitDir = path.resolve(process.env.CHRONOS_REPO_PATH);
    if (fs.existsSync(explicitDir)) {
      searchDirs.push(explicitDir);
    }
  }

  if (directory) searchDirs.push(directory);

  searchDirs.push(process.cwd());
  if (process.env.PWD) searchDirs.push(process.env.PWD);

  searchDirs.push(
    path.join(os.homedir() || process.env.HOME || '', 'program', 'chronos-graph'),
    path.join(os.homedir() || process.env.HOME || '', 'chronos-graph')
  );

  const uniqueDirs = [];
  for (const dir of searchDirs) {
    if (!dir) continue;
    try {
      const resolved = path.resolve(dir);
      if (fs.existsSync(resolved) && !uniqueDirs.includes(resolved)) {
        uniqueDirs.push(resolved);
      }
    } catch (e) {
      // Ignore resolution errors for invalid paths
    }
  }

  return uniqueDirs;
}


// Core logic for tool evaluation
async function evaluateTool(toolCall) {
  logDebug("evaluateTool started");
  return new Promise((resolve, reject) => {
    const http = require('node:http');
    const postData = JSON.stringify(toolCall);

    const options = {
      hostname: '127.0.0.1',
      port: parseInt(gatewayPort, 10),
      path: '/evaluate',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
        ...(process.env.MCP_GATEWAY_API_KEY ? { 'Authorization': `Bearer ${process.env.MCP_GATEWAY_API_KEY}` } : {})
      },
      timeout: 45000
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => {
        data += chunk;
      });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`Server returned status code ${res.statusCode}: ${data}`));
          return;
        }
        try {
          const result = JSON.parse(data);
          logDebug(`evaluateTool raw output (http): ${JSON.stringify(result)}`);
          if (result.decision === 'allow' || result.decision === 'ask') {
            resolve({
              status: result.decision,
              reason: result.reason,
              decision: result.decision,
              ask_message: result.ask_message
            });
          } else {
            resolve({
              status: 'deny',
              reason: result.reason,
              decision: result.decision
            });
          }
        } catch (e) {
          reject(new Error(`Failed to parse response: ${e.message}. Data: ${data}`));
        }
      });
    });

    req.on('error', (e) => {
      reject(e);
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Evaluation request timed out after 45000ms'));
    });

    req.write(postData);
    req.end();
  });
}

// Global reference variables to store client/directory if initialized via function
let globalClient = null;
let globalDirectory = null;
let globalInput = null;
if (!global.__chronos_active_evaluations) {
  global.__chronos_active_evaluations = new Set();
}
const activeEvaluations = global.__chronos_active_evaluations;

// Helper to show TUI toast message with slight delay to ensure TUI layer is ready
function showToast(message, variant = "info") {
  if (!globalClient) return;
  setTimeout(async () => {
    try {
      await globalClient.tui.showToast({
        body: {
          title: "Chronos Gate",
          message: message,
          variant: variant,
          duration: 3000
        }
      });
    } catch (e) {
      logDebug(`Failed to show toast: ${e.message}`);
    }
  }, 500);
}

let isSpawning = false;

// Helper to check gateway status and start it if offline
function checkAndStartGateway() {
  const net = require('node:net');
  const clientSocket = new net.Socket();
  clientSocket.setTimeout(1000);
  clientSocket.once('connect', () => {
    clientSocket.destroy();
    logDebug(`Gateway is already running (port ${gatewayPort} responds).`);
    showToast(`Gateway is already running (port ${gatewayPort}).`, "success");
  }).once('error', (err) => {
    clientSocket.destroy();
    if (isSpawning) {
      logDebug("Gateway auto-start is already in progress. Skipping duplicate spawn.");
      return;
    }
    isSpawning = true;
    setTimeout(() => { isSpawning = false; }, 15000);
    logDebug(`Gateway is offline. Attempting auto-start: ${err.message}`);
    showToast("Gateway is offline. Auto-starting...", "warning");
    try {
      const errLogPath = path.join(os.homedir() || process.env.HOME || '', '.config', 'opencode', 'gateway-spawn-error.log');
      const errLog = fs.openSync(errLogPath, 'a');

      const validSearchDirs = getChronosSearchDirs();

      let projectDir = null;
      let loadedEnv = {};

      for (const dir of validSearchDirs) {
        const envPath = path.join(dir, '.env');
        if (fs.existsSync(envPath)) {
          const tempEnv = loadEnvFile(envPath);
          if (tempEnv.STORAGE_BACKEND || tempEnv.MCP_GATEWAY_PORT || tempEnv.CHRONOS_INGESTION_MODE) {
            projectDir = dir;
            loadedEnv = tempEnv;
            logDebug(`Found correct .env in: ${dir}`);
            break;
          } else {
            logDebug(`Skipped .env in ${dir} (missing chronos-graph config keys).`);
          }
        }
      }

      if (!projectDir) {
        logDebug("Warning: Could not locate chronos-graph project directory with .env file. Falling back to CHRONOS_REPO_PATH or CWD.");
        projectDir = process.env.CHRONOS_REPO_PATH || process.cwd() || process.env.HOME;
      }

      const localVenvGateway = path.join(projectDir, '.venv', 'bin', 'chronos-gate');
      let gatewayCmd = 'uvx';
      let gatewayArgs = [
        "--quiet",
        "--from", `git+https://github.com/yohi/chronos-gate.git@${process.env.CHRONOS_GATEWAY_GIT_REF || 'master'}`,
        "chronos-gate", "run"
      ];

      if (fs.existsSync(localVenvGateway)) {
        gatewayCmd = localVenvGateway;
        gatewayArgs = ["run"];
        logDebug(`Using local venv gateway: ${gatewayCmd}`);
      } else {
        const localBinUvx = path.join(os.homedir() || process.env.HOME || '', '.local', 'bin', 'uvx');
        gatewayCmd = fs.existsSync(localBinUvx) ? localBinUvx : 'uvx';
        logDebug(`Using uvx fallback gateway: ${gatewayCmd}`);
      }

      const localBinDir = path.join(os.homedir() || process.env.HOME || '', '.local', 'bin');
      const currentPath = process.env.PATH || '';
      const newPath = currentPath.includes(localBinDir) ? currentPath : `${localBinDir}:${currentPath}`;

      const gatewayProc = spawn(gatewayCmd, gatewayArgs, {
        cwd: projectDir,
        detached: true,
        stdio: ['ignore', errLog, errLog],
        env: {
          ...process.env,
          ...loadedEnv,
          PATH: newPath
        }
      });
      gatewayProc.on('error', (err) => {
        logDebug(`Gateway spawn error event: ${err.message}`);
        showToast(`Gateway auto-start process encountered an error: ${err.message}`, "error");
      });
      logDebug(`Gateway spawn process initialized (using: ${gatewayCmd}) in cwd: ${projectDir}.`);
      showToast("Gateway auto-start process initialized.", "info");
      gatewayProc.unref();
    } catch (spawnError) {
      logDebug(`Gateway spawn sync exception: ${spawnError.message}`);
      showToast(`Failed to initialize gateway auto-start: ${spawnError.message}`, "error");
    }
  }).connect(parseInt(gatewayPort, 10), '127.0.0.1');
}

const permissionAskHook = async (permission, output) => {
  logDebug(`permission.ask hook invoked (standalone/direct) for type: ${permission.type}`);
  try {
    let toolCall = null;
    if (permission.type === "mcp" || permission.type === "tool") {
      toolCall = {
        tool_name: permission.metadata?.tool || permission.pattern || permission.id,
        tool_input: permission.metadata?.arguments || {}
      };
    } else if (permission.type === "command" || permission.type === "bash" || permission.type === "execute") {
      toolCall = {
        tool_name: "bash",
        tool_input: {
          command: permission.metadata?.command || permission.pattern || ""
        }
      };
    } else {
      toolCall = {
        tool_name: permission.type,
        tool_input: {
          path: permission.pattern || ""
        }
      };
    }

    if (toolCall) {
      logDebug(`Evaluating tool (direct hook): ${toolCall.tool_name}`);
      const result = await evaluateTool(toolCall);
      if (result.status === 'allow') {
        output.status = 'allow';
      } else if (result.status === 'ask') {
        output.status = 'ask';
        output.reason = result.ask_message || "Verification required";
        if (result.ask_message) {
          showToast(`Evaluation Check: ${result.ask_message}`, "warning");
        }
      } else {
        output.status = 'deny';
        output.reason = result.reason;
        logDebug(`Permission denied: ${result.reason}`);
        if (result.reason) {
          showToast(`Permission denied: ${result.reason}`, "error");
        }
      }
    }
  } catch (err) {
    logDebug(`Evaluation error: ${err.message}. Defaulting to deny for safety.`);
    showToast(`Evaluation System Error: ${err.message}`, "error");
    output.status = 'deny';
    output.reason = `Security gate evaluation error: ${err.message}`;
  }
};

// --------------------------------------------------------------------------
// OpenCode Plugin Specification compliant export
// --------------------------------------------------------------------------
module.exports = {
  id: "@yohi/opencode-plugin-chronos-gate",
  "permission.ask": permissionAskHook,
  server: async (input, _options) => {
    logDebug("Plugin activation function (init) called.");
    if (input) {
      globalClient = input.client;
      globalDirectory = input.directory;
      globalInput = input;
    }

    try {
      checkAndStartGateway();
    } catch (err) {
      logDebug(`Error starting gateway on init: ${err.message}`);
    }

    return {
      // Security Evaluation Gate hook
      "permission.ask": async (permission, output) => {
        logDebug(`permission.ask hook invoked (nested in server) for type: ${permission.type}`);
        return permissionAskHook(permission, output);
      }
    };
  }
};
