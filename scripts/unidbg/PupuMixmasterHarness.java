package com.pupu.harness;

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
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Iterator;
import java.util.Map;

public class PupuMixmasterHarness extends AbstractJni {
    private static final int SDK = 23;

    private final AndroidEmulator emulator;
    private final VM vm;
    private final DvmClass vortex;

    private PupuMixmasterHarness(File libFile) {
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
        vm.setVerbose(true);

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
                System.out.println("[stub] " + name + " => 0");
                return 0;
            }
        });
    }

    private UnidbgPointer retConst(SvcMemory svcMemory, String name, long value) {
        return svcMemory.registerSvc(new Arm64Svc(name) {
            @Override
            public long handle(Emulator<?> emulator) {
                System.out.println("[stub] " + name + " => " + value);
                return value;
            }
        });
    }

    private UnidbgPointer fakePtr(SvcMemory svcMemory, String name, long value) {
        return svcMemory.registerSvc(new Arm64Svc(name) {
            @Override
            public long handle(Emulator<?> emulator) {
                System.out.println("[stub] " + name + " => 0x" + Long.toHexString(value));
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

    private DvmObject<?> contextObject() {
        return vm.resolveClass("android/content/Context").newObject("pupu-context-stub");
    }

    @Override
    public DvmObject<?> callStaticObjectMethod(BaseVM vm, DvmClass dvmClass, String signature, VarArg varArg) {
        System.out.println("[callStaticObjectMethod] " + signature);
        if ("android/app/ActivityThread->currentApplication()Landroid/app/Application;".equals(signature)) {
            return vm.resolveClass("android/app/Application").newObject("pupu-application-stub");
        }
        return super.callStaticObjectMethod(vm, dvmClass, signature, varArg);
    }

    @Override
    public DvmObject<?> callObjectMethodV(BaseVM vm, DvmObject<?> dvmObject, String signature, VaList vaList) {
        System.out.println("[callObjectMethodV] " + signature + " this=" + dvmObject);
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
        return super.callObjectMethodV(vm, dvmObject, signature, vaList);
    }

    @Override
    public boolean callBooleanMethodV(BaseVM vm, DvmObject<?> dvmObject, String signature, VaList vaList) {
        System.out.println("[callBooleanMethodV] " + signature + " this=" + dvmObject);
        Object value = dvmObject == null ? null : dvmObject.getValue();
        if (signature.endsWith("->hasNext()Z") && value instanceof Iterator) {
            return ((Iterator<?>) value).hasNext();
        }
        return super.callBooleanMethodV(vm, dvmObject, signature, vaList);
    }
    @Override
    public DvmObject<?> callObjectMethod(BaseVM vm, DvmObject<?> dvmObject, String signature, VarArg varArg) {
        System.out.println("[callObjectMethod] " + signature + " this=" + dvmObject);
        if ("android/content/Context->getPackageName()Ljava/lang/String;".equals(signature)) {
            return new StringObject(vm, "com.pupumall.customer");
        }
        if ("android/content/Context->getFilesDir()Ljava/io/File;".equals(signature)
                || "android/content/Context->getCacheDir()Ljava/io/File;".equals(signature)) {
            return ProxyDvmObject.createObject(vm, new File("target/pupu-harness-files"));
        }
        if ("java/io/File->getAbsolutePath()Ljava/lang/String;".equals(signature)) {
            Object value = dvmObject.getValue();
            return new StringObject(vm, value instanceof File ? ((File) value).getAbsolutePath() : "target/pupu-harness-files");
        }
        return super.callObjectMethod(vm, dvmObject, signature, varArg);
    }

    @Override
    public int callIntMethod(BaseVM vm, DvmObject<?> dvmObject, String signature, VarArg varArg) {
        System.out.println("[callIntMethod] " + signature + " this=" + dvmObject);
        if ("java/util/HashMap->size()I".equals(signature) && dvmObject.getValue() instanceof Map) {
            return ((Map<?, ?>) dvmObject.getValue()).size();
        }
        return super.callIntMethod(vm, dvmObject, signature, varArg);
    }

    @Override
    public boolean callBooleanMethod(BaseVM vm, DvmObject<?> dvmObject, String signature, VarArg varArg) {
        System.out.println("[callBooleanMethod] " + signature + " this=" + dvmObject);
        return super.callBooleanMethod(vm, dvmObject, signature, varArg);
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            throw new IllegalArgumentException("Usage: PupuMixmasterHarness <libmixmaster.so> [path] [deviceFeed]");
        }
        File lib = new File(args[0]).getCanonicalFile();
        System.out.println("[pupu] lib=" + lib);
        PupuMixmasterHarness harness = new PupuMixmasterHarness(lib);
        try {
            System.out.println("[pupu] JNI_OnLoad ok");
            harness.thrust();
            System.out.println("[pupu] thrust ok");
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put("pp-time", "1710000000000");
            headers.put("pp-seqid", "00000000-0000-0000-0000-000000000000");
            headers.put("user-agent", "pupu-harness");
            String path = args.length > 1 ? args[1] : "/client/product/storeproduct/detail";
            String deviceFeed = args.length > 2 ? args[2] : "{}";
            String seal = harness.swindle(headers, path, deviceFeed);
            System.out.println("[pupu] swindle=" + seal);
        } finally {
            harness.close();
        }
    }
}
