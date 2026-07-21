// Native buffer tracer for SecNeo-style early unpacking.
// Hooks libc/linker allocation/copy/file APIs and dumps only buffers that
// contain DEX/CDex or known Pupu/SecNeo markers.

(function () {
  const MAX_CAPTURE_BYTES = 32 * 1024 * 1024;
  const MAX_SCAN_BYTES = 4 * 1024 * 1024;
  const MIN_INTERESTING_SIZE = 0x400;
  const dumped = {};
  const fdPaths = {};
  const fdOffsets = {};

  const MARKERS = [
    {name: "dex", bytes: [0x64, 0x65, 0x78, 0x0a]},
    {name: "cdex", bytes: [0x63, 0x64, 0x65, 0x78]},
    {name: "dexdata0", bytes: [0x64, 0x65, 0x78, 0x64, 0x61, 0x74, 0x61, 0x30]},
    {name: "fdex", bytes: [0x66, 0x64, 0x65, 0x78]},
    {name: "HEADER_SEAL", text: "HEADER_SEAL"},
    {name: "HEADER_SIGN", text: "HEADER_SIGN"},
    {name: "HeaderSignInterceptor", text: "HeaderSignInterceptor"},
    {name: "MNetSecurityUtil", text: "MNetSecurityUtil"},
    {name: "seal-v3", text: "seal-v3"},
    {name: "sign-v3", text: "sign-v3"},
    {name: "pp-seqid", text: "pp-seqid"},
    {name: "pp-time", text: "pp-time"},
    {name: "com.pupumall", text: "com.pupumall"}
  ];

  function nowIso() {
    return new Date().toISOString();
  }

  function ptrKey(addr, size) {
    return addr.toString() + ":" + size;
  }

  function bytesFor(marker) {
    if (marker.bytes) return marker.bytes;
    const out = [];
    for (let i = 0; i < marker.text.length; i++) out.push(marker.text.charCodeAt(i) & 0xff);
    return out;
  }

  function indexOfBytes(buf, pat) {
    if (!buf || !pat || buf.length < pat.length) return -1;
    const first = pat[0];
    outer:
    for (let i = 0; i <= buf.length - pat.length; i++) {
      if (buf[i] !== first) continue;
      for (let j = 1; j < pat.length; j++) {
        if (buf[i + j] !== pat[j]) continue outer;
      }
      return i;
    }
    return -1;
  }

  function findMarker(bytes) {
    const u8 = new Uint8Array(bytes);
    for (const marker of MARKERS) {
      const idx = indexOfBytes(u8, bytesFor(marker));
      if (idx >= 0) return {name: marker.name, offset: idx};
    }
    return null;
  }

  function declaredDexSize(addr, maxSize) {
    try {
      const magic = addr.readByteArray(4);
      const marker = findMarker(magic);
      if (!marker || (marker.name !== "dex" && marker.name !== "cdex")) return 0;
      const size = addr.add(0x20).readU32();
      if (size >= 0x70 && size <= maxSize && size <= MAX_CAPTURE_BYTES) return size;
    } catch (_) {}
    return 0;
  }

  function rangeForAddress(addr) {
    try {
      return Process.findRangeByAddress(addr);
    } catch (_) {
      return null;
    }
  }

  function dumpBuffer(addr, size, reason, extra) {
    if (addr.isNull() || size < MIN_INTERESTING_SIZE) return;
    const range = rangeForAddress(addr);
    if (!range || range.protection.indexOf("r") < 0) return;
    const maxReadable = range.base.add(range.size).sub(addr).toInt32();
    if (maxReadable <= 0) return;
    let captureSize = Math.min(size, maxReadable, MAX_CAPTURE_BYTES);
    const dexSize = declaredDexSize(addr, captureSize);
    if (dexSize) captureSize = dexSize;
    const key = ptrKey(addr, captureSize);
    if (dumped[key]) return;

    let data = null;
    let marker = null;
    try {
      const scanSize = Math.min(captureSize, MAX_SCAN_BYTES);
      const sample = addr.readByteArray(scanSize);
      marker = findMarker(sample);
      if (!marker) return;
      data = addr.readByteArray(captureSize);
    } catch (_) {
      return;
    }

    dumped[key] = true;
    send({
      kind: "native_buffer_dump",
      timestamp: nowIso(),
      reason: reason,
      address: addr.toString(),
      requested_size: size,
      dumped_size: captureSize,
      marker: marker.name,
      marker_offset: marker.offset,
      protection: range.protection,
      range_base: range.base.toString(),
      range_size: range.size,
      file: range.file ? range.file.path : null,
      extra: extra || {}
    }, data);
  }

  function dumpAroundMarker(addr, size, reason, extra) {
    if (addr.isNull() || size < MIN_INTERESTING_SIZE) return;
    const range = rangeForAddress(addr);
    if (!range || range.protection.indexOf("r") < 0) return;
    const maxReadable = Math.min(range.base.add(range.size).sub(addr).toInt32(), size, MAX_SCAN_BYTES);
    if (maxReadable < MIN_INTERESTING_SIZE) return;
    try {
      const sample = addr.readByteArray(maxReadable);
      const marker = findMarker(sample);
      if (!marker) return;
      const startOffset = Math.max(0, marker.offset - 0x1000);
      const dumpAddr = addr.add(startOffset);
      const dumpSize = Math.min(size - startOffset, MAX_CAPTURE_BYTES);
      dumpBuffer(dumpAddr, dumpSize, reason + "_marker_" + marker.name, extra);
    } catch (_) {}
  }

  function scanChunksForMarkers(addr, size, reason, extra) {
    if (addr.isNull() || size < MIN_INTERESTING_SIZE) return;
    const range = rangeForAddress(addr);
    if (!range || range.protection.indexOf("r") < 0) return;
    const maxReadable = Math.min(range.base.add(range.size).sub(addr).toInt32(), size);
    if (maxReadable < MIN_INTERESTING_SIZE) return;
    const chunkSize = 1024 * 1024;
    const overlap = 0x100;
    for (let off = 0; off < maxReadable; off += chunkSize - overlap) {
      const current = addr.add(off);
      const currentSize = Math.min(chunkSize, maxReadable - off);
      try {
        const sample = current.readByteArray(currentSize);
        const marker = findMarker(sample);
        if (!marker) continue;
        const startOffset = Math.max(0, off + marker.offset - 0x1000);
        const dumpAddr = addr.add(startOffset);
        const dumpSize = Math.min(maxReadable - startOffset, MAX_CAPTURE_BYTES);
        dumpBuffer(dumpAddr, dumpSize, reason + "_chunk_marker_" + marker.name, extra);
      } catch (_) {}
    }
  }

  function globalExport(name) {
    if (Module.findGlobalExportByName) return Module.findGlobalExportByName(name);
    if (Module.findExportByName) return Module.findExportByName(null, name);
    return null;
  }

  function hookDlopen(name) {
    const fn = globalExport(name);
    if (!fn) {
      send({kind: "hook_missing", timestamp: nowIso(), api: name});
      return;
    }
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.path = args[0].isNull() ? "" : args[0].readCString();
      },
      onLeave(retval) {
        const path = this.path || "";
        if (path.indexOf("DexHelper") >= 0 || path.indexOf("base.apk") >= 0) {
          send({kind: "dlopen", timestamp: nowIso(), api: name, path: path, retval: retval.toString()});
          setTimeout(function () { scanAll("after_" + name); }, 10);
          setTimeout(function () { scanAll("late_after_" + name); }, 100);
        }
      }
    });
  }

  function hookOpen(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.path = args[0].isNull() ? "" : args[0].readCString();
      },
      onLeave(retval) {
        const fd = retval.toInt32();
        if (fd >= 0 && this.path) {
          fdPaths[fd] = this.path;
          fdOffsets[fd] = 0;
          noteFd("open", fd, this.path);
        }
      }
    });
  }

  function hookOpenAt() {
    const fn = globalExport("openat");
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: "openat", address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.path = args[1].isNull() ? "" : args[1].readCString();
      },
      onLeave(retval) {
        const fd = retval.toInt32();
        if (fd >= 0 && this.path) {
          fdPaths[fd] = this.path;
          fdOffsets[fd] = 0;
          noteFd("openat", fd, this.path);
        }
      }
    });
  }

  function noteFd(api, fd, path) {
    if (!path) return;
    if (
      path.indexOf("base.apk") >= 0 ||
      path.indexOf("classes") >= 0 ||
      path.indexOf("DexHelper") >= 0 ||
      path.indexOf("memfd") >= 0 ||
      path.indexOf("pupu") >= 0
    ) {
      send({kind: "fd_path", timestamp: nowIso(), api: api, fd: fd, path: path});
    }
  }

  function isInterestingPath(path) {
    return (
      path.indexOf("base.apk") >= 0 ||
      path.indexOf("classes") >= 0 ||
      path.indexOf("DexHelper") >= 0 ||
      path.indexOf("memfd") >= 0 ||
      path.indexOf("pupu") >= 0
    );
  }

  function hookRead() {
    const fn = globalExport("read");
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: "read", address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
      },
      onLeave(retval) {
        const n = retval.toInt32();
        if (n < MIN_INTERESTING_SIZE) return;
        const path = fdPaths[this.fd] || "";
        const startOffset = fdOffsets[this.fd] || 0;
        fdOffsets[this.fd] = startOffset + n;
        if (isInterestingPath(path)) {
          dumpAroundMarker(this.buf, n, "read", {fd: this.fd, path: path, offset: startOffset});
          scanChunksForMarkers(this.buf, n, "read", {fd: this.fd, path: path, offset: startOffset});
        }
      }
    });
  }

  function hookPread(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
        this.size = args[2].toInt32();
        this.offset = args[3].toString();
      },
      onLeave(retval) {
        const n = retval.toInt32();
        if (n < MIN_INTERESTING_SIZE) return;
        const path = fdPaths[this.fd] || "";
        if (isInterestingPath(path)) {
          dumpAroundMarker(this.buf, n, name, {fd: this.fd, path: path, offset: this.offset});
          scanChunksForMarkers(this.buf, n, name, {fd: this.fd, path: path, offset: this.offset});
        }
      }
    });
  }

  function hookWrite(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
        this.size = args[2].toInt32();
      },
      onLeave(retval) {
        const n = retval.toInt32();
        if (n < MIN_INTERESTING_SIZE) return;
        const path = fdPaths[this.fd] || "";
        const startOffset = fdOffsets[this.fd] || 0;
        fdOffsets[this.fd] = startOffset + n;
        if (isInterestingPath(path)) {
          dumpAroundMarker(this.buf, Math.min(n, this.size), name, {
            fd: this.fd,
            path: path,
            offset: startOffset
          });
          scanChunksForMarkers(this.buf, Math.min(n, this.size), name, {
            fd: this.fd,
            path: path,
            offset: startOffset
          });
        }
      }
    });
  }

  function hookPwrite(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
        this.size = args[2].toInt32();
        this.offset = args[3].toString();
      },
      onLeave(retval) {
        const n = retval.toInt32();
        if (n < MIN_INTERESTING_SIZE) return;
        const path = fdPaths[this.fd] || "";
        if (isInterestingPath(path)) {
          dumpAroundMarker(this.buf, Math.min(n, this.size), name, {
            fd: this.fd,
            path: path,
            offset: this.offset
          });
          scanChunksForMarkers(this.buf, Math.min(n, this.size), name, {
            fd: this.fd,
            path: path,
            offset: this.offset
          });
        }
      }
    });
  }

  function hookMemfdCreate() {
    const fn = globalExport("memfd_create");
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: "memfd_create", address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.name = args[0].isNull() ? "" : args[0].readCString();
      },
      onLeave(retval) {
        const fd = retval.toInt32();
        if (fd >= 0) {
          fdPaths[fd] = "memfd:" + (this.name || "anonymous");
          fdOffsets[fd] = 0;
          noteFd("memfd_create", fd, fdPaths[fd]);
        }
      }
    });
  }

  function hookFtruncate(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.length = args[1].toString();
      },
      onLeave(retval) {
        const path = fdPaths[this.fd] || "";
        if (isInterestingPath(path)) {
          send({
            kind: "fd_resize",
            timestamp: nowIso(),
            api: name,
            fd: this.fd,
            path: path,
            length: this.length,
            retval: retval.toString()
          });
        }
      }
    });
  }

  function hookLseek(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.offset = args[1].toInt32();
        this.whence = args[2].toInt32();
      },
      onLeave(retval) {
        const result = retval.toInt32();
        if (result >= 0) fdOffsets[this.fd] = result;
      }
    });
  }

  function hookClose() {
    const fn = globalExport("close");
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: "close", address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.fd = args[0].toInt32();
        this.path = fdPaths[this.fd] || "";
      },
      onLeave() {
        if (isInterestingPath(this.path)) {
          send({kind: "fd_close", timestamp: nowIso(), fd: this.fd, path: this.path});
        }
        delete fdPaths[this.fd];
        delete fdOffsets[this.fd];
      }
    });
  }

  function hookCopy(name, dstIndex, srcIndex, sizeIndex) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.dst = args[dstIndex];
        this.src = args[srcIndex];
        this.size = args[sizeIndex].toInt32();
      },
      onLeave() {
        const n = this.size;
        if (n < MIN_INTERESTING_SIZE || n > MAX_CAPTURE_BYTES) return;
        dumpBuffer(this.dst, n, name + "_dst", {});
        dumpAroundMarker(this.dst, n, name + "_dst", {});
      }
    });
  }

  function hookMprotect() {
    const fn = globalExport("mprotect");
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: "mprotect", address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.addr = args[0];
        this.size = args[1].toInt32();
        this.prot = args[2].toInt32();
        if (this.size >= MIN_INTERESTING_SIZE && this.size <= 256 * 1024 * 1024) {
          dumpBuffer(this.addr, this.size, "mprotect_before", {prot: this.prot});
          dumpAroundMarker(this.addr, this.size, "mprotect_before", {prot: this.prot});
          scanChunksForMarkers(this.addr, this.size, "mprotect_before", {prot: this.prot});
        }
      },
      onLeave(retval) {
        if (retval.toInt32() !== 0) return;
        if (this.size < MIN_INTERESTING_SIZE || this.size > 256 * 1024 * 1024) return;
        dumpBuffer(this.addr, this.size, "mprotect", {prot: this.prot});
        dumpAroundMarker(this.addr, this.size, "mprotect", {prot: this.prot});
      }
    });
  }

  function hookMmap(name) {
    const fn = globalExport(name);
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: name, address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.size = args[1].toInt32();
        this.fd = args[4].toInt32();
        this.offset = args[5].toString();
      },
      onLeave(retval) {
        if (retval.isNull()) return;
        if (this.size < MIN_INTERESTING_SIZE || this.size > MAX_CAPTURE_BYTES) return;
        const path = fdPaths[this.fd] || "";
        setTimeout(() => {
          const extra = {fd: this.fd, path: path, offset: this.offset};
          if (isInterestingPath(path)) {
            if (this.size <= MAX_CAPTURE_BYTES) dumpBuffer(retval, this.size, name, extra);
            dumpAroundMarker(retval, this.size, name, extra);
            scanChunksForMarkers(retval, this.size, name, extra);
          }
        }, 1);
      }
    });
  }

  function hookMunmap() {
    const fn = globalExport("munmap");
    if (!fn) return;
    send({kind: "hook_ready", timestamp: nowIso(), api: "munmap", address: fn.toString()});
    Interceptor.attach(fn, {
      onEnter(args) {
        this.addr = args[0];
        this.size = args[1].toInt32();
        if (this.size >= MIN_INTERESTING_SIZE && this.size <= 256 * 1024 * 1024) {
          dumpBuffer(this.addr, this.size, "munmap_before", {});
          dumpAroundMarker(this.addr, this.size, "munmap_before", {});
          scanChunksForMarkers(this.addr, this.size, "munmap_before", {});
        }
      }
    });
  }

  function scanAll(reason) {
    send({kind: "scan_start", timestamp: nowIso(), reason: reason});
    const ranges = Process.enumerateRanges({protection: "r--", coalesce: true})
      .concat(Process.enumerateRanges({protection: "rw-", coalesce: true}))
      .concat(Process.enumerateRanges({protection: "r-x", coalesce: true}));
    for (const range of ranges) dumpAroundMarker(range.base, range.size, "scan_" + reason, {
      file: range.file ? range.file.path : null
    });
    send({kind: "scan_done", timestamp: nowIso(), reason: reason});
  }

  hookDlopen("dlopen");
  hookDlopen("android_dlopen_ext");
  hookOpen("open");
  hookOpen("open64");
  hookOpenAt();
  hookMemfdCreate();
  hookRead();
  hookPread("pread");
  hookPread("pread64");
  hookWrite("write");
  hookPwrite("pwrite");
  hookPwrite("pwrite64");
  hookFtruncate("ftruncate");
  hookFtruncate("ftruncate64");
  hookLseek("lseek");
  hookLseek("lseek64");
  hookClose();
  hookMmap("mmap");
  hookMmap("mmap64");
  hookCopy("memcpy", 0, 1, 2);
  hookCopy("__memcpy_chk", 0, 1, 2);
  hookCopy("memmove", 0, 1, 2);
  hookMprotect();
  hookMunmap();

  send({kind: "native_buffer_dump_ready", timestamp: nowIso()});
})();
