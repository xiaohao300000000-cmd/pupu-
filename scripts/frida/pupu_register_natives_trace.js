// Trace JNI RegisterNatives mappings so native-only sign/seal entrypoints can
// be mapped back to their .so offsets without committing private captures.

(function () {
  function nowIso() {
    return new Date().toISOString();
  }

  function readJString(env, jstr) {
    if (jstr.isNull()) return null;
    const getStringUtfChars = new NativeFunction(env.add(Process.pointerSize * 169).readPointer(), "pointer", [
      "pointer",
      "pointer",
      "pointer"
    ]);
    const releaseStringUtfChars = new NativeFunction(env.add(Process.pointerSize * 170).readPointer(), "void", [
      "pointer",
      "pointer",
      "pointer"
    ]);
    const cstr = getStringUtfChars(env, jstr, NULL);
    if (cstr.isNull()) return null;
    const value = cstr.readCString();
    releaseStringUtfChars(env, jstr, cstr);
    return value;
  }

  function classNameFromJclass(env, clazz) {
    try {
      const findClass = new NativeFunction(env.add(Process.pointerSize * 6).readPointer(), "pointer", [
        "pointer",
        "pointer"
      ]);
      const getMethodId = new NativeFunction(env.add(Process.pointerSize * 33).readPointer(), "pointer", [
        "pointer",
        "pointer",
        "pointer",
        "pointer"
      ]);
      const callObjectMethod = new NativeFunction(env.add(Process.pointerSize * 34).readPointer(), "pointer", [
        "pointer",
        "pointer",
        "pointer"
      ]);
      const classClass = findClass(env, Memory.allocUtf8String("java/lang/Class"));
      const getName = getMethodId(
        env,
        classClass,
        Memory.allocUtf8String("getName"),
        Memory.allocUtf8String("()Ljava/lang/String;")
      );
      const name = callObjectMethod(env, clazz, getName);
      return readJString(env, name);
    } catch (e) {
      return null;
    }
  }

  function interestingClass(name) {
    if (!name) return false;
    return (
      name.indexOf("pupumall") >= 0 ||
      name.indexOf("tinystack") >= 0 ||
      name.indexOf("Gears") >= 0 ||
      name.indexOf("Vortex") >= 0 ||
      name.indexOf("JniLib") >= 0
    );
  }

  function hookRegisterNatives(symbol) {
    Interceptor.attach(symbol.address, {
      onEnter(args) {
        const env = args[0];
        const clazz = args[1];
        const methods = args[2];
        const count = args[3].toInt32();
        const className = classNameFromJclass(env, clazz);
        if (!interestingClass(className)) return;
        const rows = [];
        for (let i = 0; i < count; i++) {
          const base = methods.add(i * Process.pointerSize * 3);
          const name = base.readPointer().readCString();
          const sig = base.add(Process.pointerSize).readPointer().readCString();
          const fn = base.add(Process.pointerSize * 2).readPointer();
          const mod = Process.findModuleByAddress(fn);
          rows.push({
            name: name,
            signature: sig,
            function: fn.toString(),
            module: mod ? mod.name : null,
            module_path: mod ? mod.path : null,
            module_offset: mod ? fn.sub(mod.base).toString() : null
          });
        }
        send({
          kind: "register_natives",
          timestamp: nowIso(),
          symbol: symbol.name,
          class_name: className,
          count: count,
          methods: rows
        });
      }
    });
    send({kind: "hook_ready", timestamp: nowIso(), api: symbol.name, address: symbol.address.toString()});
  }

  const symbols = Module.enumerateSymbolsSync("libart.so").filter(function (s) {
    return s.name.indexOf("RegisterNatives") >= 0 && s.name.indexOf("CheckJNI") < 0;
  });
  symbols.forEach(hookRegisterNatives);
  send({kind: "register_natives_trace_ready", timestamp: nowIso(), hooks: symbols.length});
})();
