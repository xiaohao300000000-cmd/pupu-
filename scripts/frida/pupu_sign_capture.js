// Frida script for local Pupu signed-header capture.
// It observes request construction and selected signing classes, then sends
// structured events to scripts/capture_pupu_signatures.py. It does not modify
// requests or bypass transport checks.

(function () {
  const TARGET_HOST_RE = /(^|\.)pupu(api)?\.com$/i;
  const SIGN_HEADER_RE = /^(seal|seal-v2|seal-v3|sign|sign-v2|sign-v3|pp-seqid|pp-time|x-pupu-signature-value|x-pupu-signature-timestamp|x-pupu-signature-version)$/i;
  const INTERESTING_PATH_RE = /(storeproduct|shopping_cart|cart|detail_popup|purchasing_product)/i;

  function nowIso() {
    return new Date().toISOString();
  }

  function safeString(value) {
    if (value === null || value === undefined) return null;
    try {
      return String(value);
    } catch (_) {
      return "<toString failed>";
    }
  }

  function urlHost(urlText) {
    const text = safeString(urlText) || "";
    const match = text.match(/^https?:\/\/([^\/?#]+)/i);
    return match ? match[1].toLowerCase() : "";
  }

  function urlPath(urlText) {
    const text = safeString(urlText) || "";
    const match = text.match(/^https?:\/\/[^\/?#]+([^?#]*)/i);
    return match ? (match[1] || "/") : text;
  }

  function urlQueryPairs(urlText) {
    const text = safeString(urlText) || "";
    const idx = text.indexOf("?");
    if (idx < 0) return [];
    const hash = text.indexOf("#", idx);
    const query = text.slice(idx + 1, hash < 0 ? text.length : hash);
    if (!query) return [];
    return query.split("&").map(function (part) {
      const eq = part.indexOf("=");
      const k = eq < 0 ? part : part.slice(0, eq);
      const v = eq < 0 ? "" : part.slice(eq + 1);
      return [decodeURIComponent(k.replace(/\+/g, " ")), decodeURIComponent(v.replace(/\+/g, " "))];
    });
  }

  function headersToObject(headers) {
    const out = {};
    if (!headers) return out;
    try {
      const size = headers.size();
      for (let i = 0; i < size; i++) {
        out[String(headers.name(i)).toLowerCase()] = safeString(headers.value(i));
      }
    } catch (_) {
      try {
        const names = headers.names().toArray();
        for (let i = 0; i < names.length; i++) {
          const name = String(names[i]);
          out[name.toLowerCase()] = safeString(headers.get(name));
        }
      } catch (_) {}
    }
    return out;
  }

  function hasSignedHeaders(headers) {
    for (const name in headers) {
      if (SIGN_HEADER_RE.test(name)) return true;
    }
    return false;
  }

  function shouldCapture(urlText, headers) {
    const host = urlHost(urlText);
    const path = urlPath(urlText);
    if (host && !TARGET_HOST_RE.test(host)) return false;
    return hasSignedHeaders(headers) || INTERESTING_PATH_RE.test(path);
  }

  function requestToPayload(request, hookName) {
    const url = safeString(request.url());
    const headers = headersToObject(request.headers());
    if (!shouldCapture(url, headers)) return null;
    return {
      kind: "http_request",
      source: "frida_hook_capture",
      hook: hookName,
      timestamp: nowIso(),
      request: {
        method: safeString(request.method()),
        url: url,
        path: urlPath(url),
        query: urlQueryPairs(url),
        headers: headers
      }
    };
  }

  function sendRequest(request, hookName) {
    try {
      const payload = requestToPayload(request, hookName);
      if (payload) send(payload);
    } catch (e) {
      send({kind: "hook_error", hook: hookName, message: safeString(e), timestamp: nowIso()});
    }
  }

  function hookOkHttp() {
    const Builder = Java.use("okhttp3.Request$Builder");
    Builder.build.implementation = function () {
      const request = this.build();
      sendRequest(request, "okhttp3.Request$Builder.build");
      return request;
    };

    try {
      const Chain = Java.use("okhttp3.internal.http.RealInterceptorChain");
      Chain.proceed.overloads.forEach(function (overload) {
        if (overload.argumentTypes.length === 1 && overload.argumentTypes[0].name === "okhttp3.Request") {
          overload.implementation = function (request) {
            sendRequest(request, "okhttp3.internal.http.RealInterceptorChain.proceed");
            return overload.call(this, request);
          };
        }
      });
    } catch (_) {}
  }

  function hookHeaderSignInterceptor() {
    [
      "com.pupumall.adkx.http.interceptor.HeaderSignInterceptor",
      "com.pupumall.adkx.http.interceptor.TrackableHeaderSignInterceptor"
    ].forEach(function (className) {
      try {
        const Klass = Java.use(className);
        if (!Klass.intercept) return;
        Klass.intercept.overloads.forEach(function (overload) {
          overload.implementation = function () {
            send({
              kind: "sign_interceptor_call",
              source: "frida_hook_capture",
              hook: className + ".intercept",
              timestamp: nowIso()
            });
            const result = overload.apply(this, arguments);
            try {
              if (result && result.request) sendRequest(result.request(), className + ".intercept.result");
            } catch (_) {}
            return result;
          };
        });
        send({kind: "hook_ready", hook: className, timestamp: nowIso()});
      } catch (_) {}
    });
  }

  function hookSecurityUtilMethods() {
    [
      "com.pupumall.customer.tinystack.MNetSecurityUtil"
    ].forEach(function (className) {
      try {
        const Klass = Java.use(className);
        const methods = Klass.class.getDeclaredMethods();
        for (let i = 0; i < methods.length; i++) {
          const name = String(methods[i].getName());
          if (!/(sign|seal|encrypt|md5|sha|h52)/i.test(name) || !Klass[name]) continue;
          Klass[name].overloads.forEach(function (overload) {
            overload.implementation = function () {
              const args = [];
              for (let j = 0; j < arguments.length; j++) args.push(safeString(arguments[j]));
              const result = overload.apply(this, arguments);
              send({
                kind: "security_util_call",
                source: "frida_hook_capture",
                hook: className + "." + name,
                timestamp: nowIso(),
                arg_count: args.length,
                args: args,
                result: safeString(result)
              });
              return result;
            };
          });
        }
        send({kind: "hook_ready", hook: className, timestamp: nowIso()});
      } catch (_) {}
    });
  }

  Java.perform(function () {
    hookOkHttp();
    hookHeaderSignInterceptor();
    hookSecurityUtilMethods();
    send({kind: "hook_ready", hook: "pupu_sign_capture", timestamp: nowIso()});
  });
})();
