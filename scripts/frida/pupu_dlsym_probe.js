// Lightweight dlopen/dlsym probe for native-bridge startup crashes.
(function () {
  function nowIso() {
    return new Date().toISOString();
  }

  function globalExport(name) {
    if (Module.findGlobalExportByName) return Module.findGlobalExportByName(name);
    if (Module.findExportByName) return Module.findExportByName(null, name);
    return null;
  }

  function interesting(value) {
    if (!value) return false;
    return (
      value.indexOf("AFileDescriptor") >= 0 ||
      value.indexOf("RegisterNatives") >= 0 ||
      value.indexOf("Dex") >= 0 ||
      value.indexOf("JNI") >= 0 ||
      value.indexOf("android_runtime") >= 0 ||
      value.indexOf("libandroid") >= 0 ||
      value.indexOf("pupu") >= 0 ||
      value.indexOf("seal") >= 0 ||
      value.indexOf("sign") >= 0
    );
  }

  function hookDlopen(api) {
    const fn = globalExport(api);
    if (!fn) return;
    send({kind: "hook_ready", api: api, address: fn.toString(), timestamp: nowIso()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.path = args[0].isNull() ? "" : args[0].readCString();
      },
      onLeave(retval) {
        if (interesting(this.path)) {
          send({
            kind: "dlopen",
            api: api,
            path: this.path,
            retval: retval.toString(),
            timestamp: nowIso()
          });
        }
      }
    });
  }

  function hookDlsym() {
    const fn = globalExport("dlsym");
    if (!fn) return;
    send({kind: "hook_ready", api: "dlsym", address: fn.toString(), timestamp: nowIso()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.handle = args[0];
        this.name = args[1].isNull() ? "" : args[1].readCString();
      },
      onLeave(retval) {
        if (interesting(this.name)) {
          const mod = retval.isNull() ? null : Process.findModuleByAddress(retval);
          send({
            kind: "dlsym",
            handle: this.handle.toString(),
            name: this.name,
            retval: retval.toString(),
            module: mod ? mod.name : null,
            module_path: mod ? mod.path : null,
            module_base: mod ? mod.base.toString() : null,
            offset: mod ? retval.sub(mod.base).toString() : null,
            timestamp: nowIso()
          });
        }
      }
    });
  }

  hookDlopen("dlopen");
  hookDlopen("android_dlopen_ext");
  hookDlsym();
  send({kind: "dlsym_probe_ready", timestamp: nowIso()});
})();
