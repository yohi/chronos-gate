const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const test = require('node:test');

const pluginPath = path.resolve(__dirname, '../../.opencode/plugins/chronos-gate.js');

function loadPlugin() {
  delete require.cache[pluginPath];
  delete global.__chronos_active_evaluations;
  return require(pluginPath);
}

function createTuiApi() {
  let permissionAskedHandler = null;
  const replies = [];
  const toasts = [];

  return {
    api: {
      client: {
        tui: {
          showToast: async (input) => {
            toasts.push(input);
          },
        },
        v2: {
          session: {
            permission: {
              reply: async (input) => {
                replies.push(input);
              },
            },
          },
        },
      },
      event: {
        on: (name, handler) => {
          if (name === 'permission.asked') {
            permissionAskedHandler = handler;
          }
          return () => {};
        },
      },
      ui: {
        toast: (input) => {
          toasts.push(input);
        },
      },
    },
    getPermissionAskedHandler: () => permissionAskedHandler,
    replies,
  };
}

function createPermissionEvent() {
  return {
    properties: {
      id: 'req_123',
      sessionID: 'ses_123',
      permission: {
        type: 'command',
        pattern: 'pwd',
        metadata: {
          command: 'pwd',
        },
      },
    },
  };
}

async function withGateway(decision, callback) {
  const originalPort = process.env.MCP_GATEWAY_PORT;
  const server = http.createServer((request, response) => {
    request.resume();
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ decision, reason: `${decision} reason`, ask_message: 'review required' }));
  });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.equal(typeof address, 'object');
  process.env.MCP_GATEWAY_PORT = String(address.port);

  try {
    await callback();
  } finally {
    if (originalPort === undefined) {
      delete process.env.MCP_GATEWAY_PORT;
    } else {
      process.env.MCP_GATEWAY_PORT = originalPort;
    }
    await new Promise((resolve, reject) => {
      server.close((error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  }
}

test('TUI permission.asked replies once when Chronos Gate allows the command', async () => {
  await withGateway('allow', async () => {
    const plugin = loadPlugin();
    const { api, getPermissionAskedHandler, replies } = createTuiApi();

    await plugin.tui(api);
    const handler = getPermissionAskedHandler();

    assert.equal(typeof handler, 'function');
    await handler(createPermissionEvent());

    assert.deepEqual(replies, [
      {
        sessionID: 'ses_123',
        requestID: 'req_123',
        body: {
          reply: 'once',
        },
      },
    ]);
  });
});

test('TUI permission.asked rejects when Chronos Gate asks for review', async () => {
  await withGateway('ask', async () => {
    const plugin = loadPlugin();
    const { api, getPermissionAskedHandler, replies } = createTuiApi();

    await plugin.server(api, {});
    const handler = getPermissionAskedHandler();

    assert.equal(typeof handler, 'function');
    await handler(createPermissionEvent());

    assert.equal(replies.length, 1);
    assert.equal(replies[0].body.reply, 'reject');
  });
});

test('TUI permission.asked rejects when Chronos Gate denies the command', async () => {
  await withGateway('deny', async () => {
    const plugin = loadPlugin();
    const { api, getPermissionAskedHandler, replies } = createTuiApi();

    await plugin.server(api, {});
    const handler = getPermissionAskedHandler();

    assert.equal(typeof handler, 'function');
    await handler(createPermissionEvent());

    assert.equal(replies.length, 1);
    assert.equal(replies[0].body.reply, 'reject');
  });
});
