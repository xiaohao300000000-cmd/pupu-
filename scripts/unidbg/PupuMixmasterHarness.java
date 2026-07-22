package com.pupu.harness;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.github.unidbg.AndroidEmulator;
import com.github.unidbg.Emulator;
import com.github.unidbg.arm.Arm64Svc;
import com.github.unidbg.arm.backend.Unicorn2Factory;
import com.github.unidbg.linux.android.AndroidEmulatorBuilder;
import com.github.unidbg.linux.android.AndroidResolver;
import com.github.unidbg.linux.android.dvm.AbstractJni;
import com.github.unidbg.linux.android.dvm.BaseVM;
import com.github.unidbg.linux.android.dvm.DalvikModule;
import com.github.unidbg.linux.android.dvm.DvmClass;
import com.github.unidbg.linux.android.dvm.DvmObject;
import com.github.unidbg.linux.android.dvm.StringObject;
import com.github.unidbg.linux.android.dvm.VM;
import com.github.unidbg.linux.android.dvm.VarArg;
import com.github.unidbg.linux.android.dvm.VaList;
import com.github.unidbg.linux.android.dvm.jni.ProxyClassFactory;
import com.github.unidbg.linux.android.dvm.jni.ProxyDvmObject;
import com.github.unidbg.memory.Memory;
import com.github.unidbg.memory.SvcMemory;
import com.github.unidbg.pointer.UnidbgPointer;

import java.io.File;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

public class PupuMixmasterHarness extends AbstractJni {
    private static final int SDK = 23;

    private final AndroidEmulator emulator;
    private final VM vm;
    private final DvmClass vortex;

    private PupuMixmasterHarness(File libFile, boolean verbose) {
        emulator = AndroidEmulatorBuilder.for64Bit()
                .setProcessName("com.pupumall.customer")
                .addBackendFactory(new Unicorn2Factory(true))
                .build();
        Memory memory = emulator.getMemory();
        memory.setLibraryResolver(new AndroidResolver(SDK));
        registerAndroidNativeStubs(memory);

        vm = emulator.createDalvikVM();
        ProxyClassFactory classFactory = new ProxyClassFactory();
        classFactory.setFallbackJni(this);
        vm.setDvmClassFactory(classFactory);
        vm.setJni(this);
        vm.setVerbose(verbose);

        DalvikModule dm = vm.loadLibrary(libFile, false);
        vortex = vm.resolveClass("com/pupumall/tinystack/Vortex");
        dm.callJNI_OnLoad(emulator);
    }

    private void registerAndroidNativeStubs(Memory memory) {
        SvcMemory svcMemory = emulator.getSvcMemory();
        Map<String, UnidbgPointer> android = new HashMap<>();
        android.put("ASensorEventQueue_setEventRate", ret0(svcMemory, "ASensorEventQueue_setEventRate"));
        android.put("ALooper_prepare", fakePtr(svcMemory, "ALooper_prepare", 0x71000001L));
        android.put("ASensorEventQueue_enableSensor", ret0(svcMemory, "ASensorEventQueue_enableSensor"));
        android.put("ASensorManager_createEventQueue", fakePtr(svcMemory, "ASensorManager_createEventQueue", 0x71000002L));
        android.put("ASensorManager_getInstance", fakePtr(svcMemory, "ASensorManager_getInstance", 0x71000003L));
        android.put("ASensor_getMinDelay", retConst(svcMemory, "ASensor_getMinDelay", 20000));
        android.put("ASensorEventQueue_getEvents", ret0(svcMemory, "ASensorEventQueue_getEvents"));
        android.put("ALooper_pollOnce", retConst(svcMemory, "ALooper_pollOnce", -3));
        android.put("ASensorManager_destroyEventQueue", ret0(svcMemory, "ASensorManager_destroyEventQueue"));
        android.put("ASensorEventQueue_disableSensor", ret0(svcMemory, "ASensorEventQueue_disableSensor"));
        android.put("ASensorManager_getDefaultSensor", fakePtr(svcMemory, "ASensorManager_getDefaultSensor", 0x71000004L));
        memory.loadVirtualModule("libandroid.so", android);

        Map<String, UnidbgPointer> media = new HashMap<>();
        media.put("AMediaDrm_createByUUID", fakePtr(svcMemory, "AMediaDrm_createByUUID", 0x72000001L));
        media.put("AMediaDrm_getPropertyByteArray", ret0(svcMemory, "AMediaDrm_getPropertyByteArray"));
        media.put("AMediaDrm_release", ret0(svcMemory, "AMediaDrm_release"));
        memory.loadVirtualModule("libmediandk.so", media);
    }

    private UnidbgPointer ret0(SvcMemory svcMemory, String name) {
        return svcMemory.registerSvc(new Arm64Svc(name) {
            @Override
            public long handle(Emulator<?> emulator) {
                System.err.println("[stub] " + name + " => 0");
                return 0;
            }
        });
    }

    private UnidbgPointer retConst(SvcMemory svcMemory, String name, long value) {
        return svcMemory.registerSvc(new Arm64Svc(name) {
            @Override
            public long handle(Emulator<?> emulator) {
                System.err.println("[stub] " + name + " => " + value);
                return value;
            }
        });
    }

    private UnidbgPointer fakePtr(SvcMemory svcMemory, String name, long value) {
        return svcMemory.registerSvc(new Arm64Svc(name) {
            @Override
            public long handle(Emulator<?> emulator) {
                System.err.println("[stub] " + name + " => 0x" + Long.toHexString(value));
                return value;
            }
        });
    }

    private void close() throws Exception {
        emulator.close();
    }

    private void thrust() {
        vortex.callStaticJniMethod(emulator, "thrust(Landroid/content/Context;)V", contextObject());
    }

    private String swindle(Map<String, String> headers, String path, String deviceFeed) {
        StringObject out = vortex.callStaticJniMethodObject(
                emulator,
                "swindle(Landroid/content/Context;IILjava/util/HashMap;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
                contextObject(),
                0,
                0,
                ProxyDvmObject.createObject(vm, new LinkedHashMap<>(headers)),
                new StringObject(vm, path),
                new StringObject(vm, deviceFeed));
        return out == null ? null : out.getValue();
    }

    private static String hex(byte[] data) {
        StringBuilder out = new StringBuilder(data.length * 2);
        for (byte item : data) {
            int value = item & 0xff;
            if (value < 16) {
                out.append('0');
            }
            out.append(Integer.toHexString(value));
        }
        return out.toString();
    }

    private static String sha256Hex(byte[] data) throws Exception {
        return hex(MessageDigest.getInstance("SHA-256").digest(data));
    }

    private static String signV3(Map<String, String> headers) throws Exception {
        ArrayList<String> keys = new ArrayList<>(headers.keySet());
        Collections.sort(keys);
        StringBuilder canonical = new StringBuilder();
        for (String key : keys) {
            String value = headers.get(key);
            if (value == null) {
                continue;
            }
            String trimmed = value.trim();
            int byteLength = trimmed.getBytes(StandardCharsets.UTF_8).length;
            canonical.append(key.length())
                    .append(':')
                    .append(key)
                    .append('=')
                    .append(byteLength)
                    .append(':')
                    .append(trimmed)
                    .append('\n');
        }
        return sha256Hex(canonical.toString().getBytes(StandardCharsets.UTF_8));
    }

    private DvmObject<?> contextObject() {
        return vm.resolveClass("android/content/Context").newObject("pupu-context-stub");
    }

    @Override
    public DvmObject<?> callStaticObjectMethod(BaseVM vm, DvmClass dvmClass, String signature, VarArg varArg) {
        System.err.println("[callStaticObjectMethod] " + signature);
        if ("android/app/ActivityThread->currentApplication()Landroid/app/Application;".equals(signature)) {
            return vm.resolveClass("android/app/Application").newObject("pupu-application-stub");
        }
        return super.callStaticObjectMethod(vm, dvmClass, signature, varArg);
    }

    @Override
    public DvmObject<?> callObjectMethodV(BaseVM vm, DvmObject<?> dvmObject, String signature, VaList vaList) {
        System.err.println("[callObjectMethodV] " + signature + " this=" + dvmObject);
        Object value = dvmObject == null ? null : dvmObject.getValue();
        if (signature.endsWith("->iterator()Ljava/util/Iterator;") && value instanceof Iterable) {
            return ProxyDvmObject.createObject(vm, ((Iterable<?>) value).iterator());
        }
        if (signature.endsWith("->next()Ljava/lang/Object;") && value instanceof Iterator) {
            return ProxyDvmObject.createObject(vm, ((Iterator<?>) value).next());
        }
        if (signature.endsWith("->getKey()Ljava/lang/Object;") && value instanceof Map.Entry) {
            Object key = ((Map.Entry<?, ?>) value).getKey();
            return key instanceof String ? new StringObject(vm, (String) key) : ProxyDvmObject.createObject(vm, key);
        }
        if (signature.endsWith("->getValue()Ljava/lang/Object;") && value instanceof Map.Entry) {
            Object entryValue = ((Map.Entry<?, ?>) value).getValue();
            return entryValue instanceof String ? new StringObject(vm, (String) entryValue) : ProxyDvmObject.createObject(vm, entryValue);
        }
        if (signature.endsWith("->getPackageName()Ljava/lang/String;")) {
            return new StringObject(vm, "com.pupumall.customer");
        }
        if (signature.endsWith("->getFilesDir()Ljava/io/File;") || signature.endsWith("->getCacheDir()Ljava/io/File;")) {
            return ProxyDvmObject.createObject(vm, new File("target/pupu-harness-files"));
        }
        if (signature.endsWith("->getContentResolver()Landroid/content/ContentResolver;")) {
            return vm.resolveClass("android/content/ContentResolver").newObject("pupu-content-resolver-stub");
        }
        return super.callObjectMethodV(vm, dvmObject, signature, vaList);
    }

    @Override
    public boolean callBooleanMethodV(BaseVM vm, DvmObject<?> dvmObject, String signature, VaList vaList) {
        System.err.println("[callBooleanMethodV] " + signature + " this=" + dvmObject);
        Object value = dvmObject == null ? null : dvmObject.getValue();
        if (signature.endsWith("->hasNext()Z") && value instanceof Iterator) {
            return ((Iterator<?>) value).hasNext();
        }
        return super.callBooleanMethodV(vm, dvmObject, signature, vaList);
    }

    @Override
    public DvmObject<?> callObjectMethod(BaseVM vm, DvmObject<?> dvmObject, String signature, VarArg varArg) {
        System.err.println("[callObjectMethod] " + signature + " this=" + dvmObject);
        if ("android/content/Context->getPackageName()Ljava/lang/String;".equals(signature)) {
            return new StringObject(vm, "com.pupumall.customer");
        }
        if ("android/content/Context->getFilesDir()Ljava/io/File;".equals(signature)
                || "android/content/Context->getCacheDir()Ljava/io/File;".equals(signature)) {
            return ProxyDvmObject.createObject(vm, new File("target/pupu-harness-files"));
        }
        if ("android/content/Context->getContentResolver()Landroid/content/ContentResolver;".equals(signature)) {
            return vm.resolveClass("android/content/ContentResolver").newObject("pupu-content-resolver-stub");
        }
        if ("java/io/File->getAbsolutePath()Ljava/lang/String;".equals(signature)) {
            Object value = dvmObject.getValue();
            return new StringObject(vm, value instanceof File ? ((File) value).getAbsolutePath() : "target/pupu-harness-files");
        }
        return super.callObjectMethod(vm, dvmObject, signature, varArg);
    }

    @Override
    public int callIntMethod(BaseVM vm, DvmObject<?> dvmObject, String signature, VarArg varArg) {
        System.err.println("[callIntMethod] " + signature + " this=" + dvmObject);
        if ("java/util/HashMap->size()I".equals(signature) && dvmObject.getValue() instanceof Map) {
            return ((Map<?, ?>) dvmObject.getValue()).size();
        }
        return super.callIntMethod(vm, dvmObject, signature, varArg);
    }

    @Override
    public boolean callBooleanMethod(BaseVM vm, DvmObject<?> dvmObject, String signature, VarArg varArg) {
        System.err.println("[callBooleanMethod] " + signature + " this=" + dvmObject);
        return super.callBooleanMethod(vm, dvmObject, signature, varArg);
    }

    private static Map<String, String> stringMap(JSONObject object) {
        Map<String, String> out = new LinkedHashMap<>();
        if (object == null) {
            return out;
        }
        for (String key : object.keySet()) {
            Object value = object.get(key);
            if (value != null) {
                out.put(key.toLowerCase(), String.valueOf(value));
            }
        }
        return out;
    }

    private static JSONObject requestObject(JSONObject payload) {
        JSONObject request = payload.getJSONObject("request");
        return request == null ? payload : request;
    }

    private static String firstString(JSONObject object, String fallback, String... keys) {
        for (String key : keys) {
            Object value = object.get(key);
            if (value != null && !String.valueOf(value).isEmpty()) {
                return String.valueOf(value);
            }
        }
        return fallback;
    }

    private static String deviceFeed(JSONObject request) {
        String direct = firstString(request, null, "device_feed", "deviceFeed", "pvrinoypdvc_dueri");
        if (direct != null) {
            return direct;
        }
        JSONObject context = request.getJSONObject("context");
        if (context != null) {
            return firstString(context, "{}", "device_feed", "deviceFeed", "pvrinoypdvc_dueri");
        }
        return "{}";
    }

    private static String headerValue(Map<String, String> headers, String name) {
        String direct = headers.get(name);
        if (direct != null) {
            return direct;
        }
        String lower = name.toLowerCase();
        for (Map.Entry<String, String> entry : headers.entrySet()) {
            if (entry.getKey() != null && entry.getKey().toLowerCase().equals(lower)) {
                return entry.getValue();
            }
        }
        return null;
    }

    private static void putHeaderIfPresent(
            Map<String, String> source,
            Map<String, String> target,
            String outputName,
            String... sourceNames) {
        for (String sourceName : sourceNames) {
            String value = headerValue(source, sourceName);
            if (value != null) {
                target.put(outputName, value);
                return;
            }
        }
    }

    private static Map<String, String> signV3HeaderMap(Map<String, String> headers) {
        Map<String, String> out = new LinkedHashMap<>();
        putHeaderIfPresent(headers, out, "timestamp", "timestamp", "pp-time");
        putHeaderIfPresent(headers, out, "pp-suid", "pp-suid");
        putHeaderIfPresent(headers, out, "pp-version", "pp-version");
        putHeaderIfPresent(headers, out, "pp-page-name", "pp-page-name");
        putHeaderIfPresent(headers, out, "user-agent", "user-agent");
        putHeaderIfPresent(headers, out, "pp-userid", "pp-userid", "pp-user-id");
        putHeaderIfPresent(headers, out, "pp_storeid", "pp_storeid", "pp-storeid", "pp-store-id");
        putHeaderIfPresent(headers, out, "pp-placezip", "pp-placezip", "pp-place-zip");
        putHeaderIfPresent(headers, out, "pp-os", "pp-os");
        putHeaderIfPresent(headers, out, "pp_store_city_zip", "pp_store_city_zip", "pp-store-city-zip");
        putHeaderIfPresent(headers, out, "pp-placeid", "pp-placeid", "pp-place-id");
        putHeaderIfPresent(headers, out, "pp-ru-version", "pp-ru-version");
        putHeaderIfPresent(headers, out, "pp-seqid", "pp-seqid");
        putHeaderIfPresent(headers, out, "pp-nu-version", "pp-nu-version");
        return out;
    }

    private static void runSignerMode(String[] args) throws Exception {
        if (args.length < 3) {
            throw new IllegalArgumentException("Usage: PupuMixmasterHarness --signer <libmixmaster.so> <input-json-file>");
        }
        PrintStream originalOut = System.out;
        System.setOut(System.err);
        JSONObject result = new JSONObject(true);
        File lib = new File(args[1]).getCanonicalFile();
        JSONObject payload = JSON.parseObject(Files.readString(new File(args[2]).toPath(), StandardCharsets.UTF_8));
        JSONObject request = requestObject(payload);
        String path = firstString(request, "", "path", "ah", "at", "url_path", "uri");
        Map<String, String> headers = stringMap(request.getJSONObject("headers"));
        if (headers.isEmpty()) {
            headers = stringMap(request.getJSONObject("edr"));
        }
        PupuMixmasterHarness harness = new PupuMixmasterHarness(lib, false);
        try {
            harness.thrust();
            Map<String, String> signHeaders = signV3HeaderMap(headers);
            String sign = signV3(signHeaders);
            Map<String, String> sealHeaders = new LinkedHashMap<>();
            sealHeaders.put("timestamp", signHeaders.getOrDefault("timestamp", ""));
            sealHeaders.put("sign-v3", sign);
            String seal = harness.swindle(sealHeaders, path, deviceFeed(request));
            if (seal == null || seal.isEmpty()) {
                result.put("ok", false);
                result.put("error", "mixmaster_swindle_empty");
            } else {
                JSONObject signedHeaders = new JSONObject(true);
                if (signHeaders.containsKey("timestamp")) {
                    signedHeaders.put("timestamp", signHeaders.get("timestamp"));
                }
                signedHeaders.put("sign-v3", sign);
                signedHeaders.put("seal-v3", seal);
                if (headers.containsKey("pp-time")) {
                    signedHeaders.put("pp-time", headers.get("pp-time"));
                }
                JSONObject metadata = new JSONObject(true);
                metadata.put("source", "unidbg_mixmaster");
                metadata.put("path", path);
                metadata.put("native", "libmixmaster.so");
                metadata.put("sign-v3", "sha256_canonical_headers");
                result.put("signed_headers", signedHeaders);
                result.put("metadata", metadata);
            }
        } finally {
            harness.close();
            System.setOut(originalOut);
        }
        originalOut.println(result.toJSONString());
    }

    private static void runSmokeMode(String[] args) throws Exception {
        if (args.length < 1) {
            throw new IllegalArgumentException("Usage: PupuMixmasterHarness <libmixmaster.so> [path] [deviceFeed]");
        }
        File lib = new File(args[0]).getCanonicalFile();
        System.out.println("[pupu] lib=" + lib);
        PupuMixmasterHarness harness = new PupuMixmasterHarness(lib, true);
        try {
            System.out.println("[pupu] JNI_OnLoad ok");
            harness.thrust();
            System.out.println("[pupu] thrust ok");
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put("pp-time", "1710000000000");
            headers.put("pp-seqid", "00000000-0000-0000-0000-000000000000");
            headers.put("user-agent", "pupu-harness");
            String path = args.length > 1 ? args[1] : "/client/product/storeproduct/detail";
            String feed = args.length > 2 ? args[2] : "{}";
            String seal = harness.swindle(headers, path, feed);
            System.out.println("[pupu] swindle=" + seal);
        } finally {
            harness.close();
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 0 && "--signer".equals(args[0])) {
            runSignerMode(args);
            return;
        }
        runSmokeMode(args);
    }
}
