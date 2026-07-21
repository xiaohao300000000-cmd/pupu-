// Dump DEX-like memory ranges before/around SecNeo startup crash.
// Native-only Frida script: does not require Java.perform() and can run very early.

(function () {
  const DEX_MAGICS = ["dex\n", "cdex"];
  const MAX_DUMP_BYTES = 64 * 1024 * 1024;
  const dumped = {};

  function nowIso() {
    return new Date().toISOString();
  }

  function startsWithMagic(bytes) {
    if (!bytes || bytes.byteLength < 4) return null;
    const u8 = new Uint8Array(bytes);
    for (const magic of DEX_MAGICS) {
      let ok = true;
      for (let i = 0; i < magic.length; i++) {
        if (u8[i] !== magic.charCodeAt(i)) {
          ok = false;
          break;
        }
      }
      if (ok) return magic.trim();
    }
    return null;
  }

  function readU32(ptr) {
    try {
      return ptr.readU32();
    } catch (_) {
      return 0;
    }
  }

  function dexDeclaredSize(addr) {
    // Standard DEX file_size at +0x20. Compact-dex may not use it reliably.
    const size = readU32(addr.add(0x20));
    if (size > 0x70 && size <= MAX_DUMP_BYTES) return size;
    return 0;
  }

  function dumpAt(addr, range, reason) {
    const key = addr.toString();
    if (dumped[key]) return;
    dumped[key] = true;
    let size = dexDeclaredSize(addr);
    if (!size) size = Math.min(range.base.add(range.size).sub(addr).toInt32(), MAX_DUMP_BYTES);
    if (size <= 0) return;
    try {
      const data = addr.readByteArray(size);
      const magic = startsWithMagic(data);
      if (!magic) return;
      send({
        kind: "dex_dump",
        reason: reason,
        timestamp: nowIso(),
        address: addr.toString(),
        range_base: range.base.toString(),
        range_size: range.size,
        size: size,
        magic: magic,
        protection: range.protection,
        file: range.file ? range.file.path : null
      }, data);
    } catch (e) {
      send({kind: "dump_error", address: key, message: String(e), timestamp: nowIso()});
    }
  }

  function scanRange(range, reason) {
    if (range.protection.indexOf("r") < 0) return;
    let matches = [];
    for (const magic of DEX_MAGICS) {
      try {
        matches = matches.concat(Memory.scanSync(range.base, range.size, magic));
      } catch (_) {}
    }
    for (const match of matches) dumpAt(match.address, range, reason);
  }

  function scanAll(reason) {
    send({kind: "scan_start", reason: reason, timestamp: nowIso()});
    const ranges = Process.enumerateRanges({protection: "r--", coalesce: true})
      .concat(Process.enumerateRanges({protection: "rw-", coalesce: true}))
      .concat(Process.enumerateRanges({protection: "r-x", coalesce: true}));
    for (const range of ranges) scanRange(range, reason);
    send({kind: "scan_done", reason: reason, timestamp: nowIso()});
  }

  function hookDlopen(name) {
    let fn = null;
    if (Module.findGlobalExportByName) fn = Module.findGlobalExportByName(name);
    if (!fn && Module.findExportByName) fn = Module.findExportByName(null, name);
    if (!fn) return;
    Interceptor.attach(fn, {
      onEnter(args) {
        this.path = args[0].isNull() ? "" : args[0].readCString();
      },
      onLeave(retval) {
        const path = this.path || "";
        if (path.indexOf("DexHelper") >= 0 || path.indexOf("base.apk") >= 0) {
          send({kind: "dlopen", name: name, path: path, retval: retval.toString(), timestamp: nowIso()});
          setTimeout(function () { scanAll("after_" + name + "_" + path); }, 50);
          setTimeout(function () { scanAll("late_after_" + name + "_" + path); }, 500);
        }
      }
    });
  }

  hookDlopen("dlopen");
  hookDlopen("android_dlopen_ext");
  setTimeout(function () { scanAll("initial_250ms"); }, 250);
  setTimeout(function () { scanAll("initial_1000ms"); }, 1000);
})();
