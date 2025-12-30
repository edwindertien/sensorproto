let port, reader, writer;
let lines = [];
let connectButton;

function setup() {
  createCanvas(400, 200);
  connectButton = createButton('Connect to Pico');
  connectButton.mousePressed(initSerial);
  textSize(14);
}

async function initSerial() {
  try {
    port = await navigator.serial.requestPort();
    await port.open({ baudRate: 115200 });

    writer = port.writable.getWriter();
    // Ask for capabilities and start streaming in human-readable format
    await writer.write(new TextEncoder().encode("?\n"));
    await writer.write(new TextEncoder().encode("stream=1\n"));
    await writer.write(new TextEncoder().encode("format=txt\n"));
    writer.releaseLock();

    readLoop();
  } catch (err) {
    console.error("Serial error:", err);
  }
}

async function readLoop() {
  reader = port.readable.getReader();
  let decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value);
    const parts = buffer.split("\n");
    buffer = parts.pop();
    for (let line of parts) {
      let row = parseFrame(line);
      if (row) lines.push(row);
      if (lines.length > 50) lines.shift();
    }
  }
}

function parseFrame(line) {
  const m = line.match(/\{([^}]+)\}/);
  if (m) return m[1].split(',').map(Number);
  return null;
}

function draw() {
  background(20);
  fill(255);
  text("Connected frames: " + lines.length, 10, 20);
  if (lines.length > 0) {
    const last = lines[lines.length - 1];
    text("Latest frame: " + last.join(", "), 10, 50);
  }
}
