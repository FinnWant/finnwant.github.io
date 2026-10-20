// Contact form backend for finnwantland.dev.
// Verifies the Cloudflare Turnstile token server-side, then emails the message
// to TO_ADDRESS through the send_email binding. GitHub Pages can't run server
// code, so this lives on Cloudflare Workers and is deployed separately.

const SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const MAX_LEN = { name: 100, email: 254, message: 5000 };

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = env.ALLOWED_ORIGINS.split(",").map((o) => o.trim());
  return {
    "Access-Control-Allow-Origin": allowed.includes(origin) ? origin : allowed[0],
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function reply(request, env, status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(request, env) },
  });
}

// Strip line breaks so visitor input can't inject extra email headers.
const oneLine = (s) => s.replace(/[\r\n]+/g, " ").trim();

async function verifyTurnstile(token, ip, env) {
  const body = new FormData();
  body.append("secret", env.TURNSTILE_SECRET);
  body.append("response", token);
  if (ip) body.append("remoteip", ip);
  const res = await fetch(SITEVERIFY_URL, { method: "POST", body });
  return res.json();
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }
    if (request.method !== "POST") {
      return reply(request, env, 405, { success: false, message: "Method not allowed" });
    }

    let data;
    try {
      data = await request.json();
    } catch {
      return reply(request, env, 400, { success: false, message: "Invalid request" });
    }

    // Honeypot: real visitors never see this field. Pretend success so bots move on.
    if (data.botcheck) return reply(request, env, 200, { success: true });

    const name = oneLine(String(data.name || ""));
    const email = oneLine(String(data.email || ""));
    const message = String(data.message || "").trim();
    const token = String(data["cf-turnstile-response"] || "");

    if (!name || !message || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return reply(request, env, 400, { success: false, message: "Please fill in every field." });
    }
    if (name.length > MAX_LEN.name || email.length > MAX_LEN.email || message.length > MAX_LEN.message) {
      return reply(request, env, 400, { success: false, message: "Message is too long." });
    }
    if (!token) {
      return reply(request, env, 400, { success: false, message: "Please complete the captcha." });
    }

    const outcome = await verifyTurnstile(token, request.headers.get("CF-Connecting-IP"), env);
    if (!outcome.success) {
      console.warn("Turnstile rejected", outcome["error-codes"]);
      return reply(request, env, 403, { success: false, message: "Captcha check failed — please try again." });
    }

    try {
      await env.EMAIL.send({
        to: env.TO_ADDRESS,
        from: env.FROM_ADDRESS,
        replyTo: email,
        subject: `Website message from ${name}`,
        text: `Name: ${name}\nEmail: ${email}\n\n${message}`,
      });
    } catch (err) {
      console.error("Email send failed", err.code, err.message);
      return reply(request, env, 502, { success: false, message: "Couldn't send right now." });
    }

    return reply(request, env, 200, { success: true });
  },
};
