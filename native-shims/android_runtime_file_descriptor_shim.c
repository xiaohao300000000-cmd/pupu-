#include <jni.h>

static jfieldID find_fd_field(JNIEnv *env, jclass cls) {
  jfieldID field = (*env)->GetFieldID(env, cls, "descriptor", "I");
  if ((*env)->ExceptionCheck(env)) {
    (*env)->ExceptionClear(env);
  }
  if (field != NULL) {
    return field;
  }

  field = (*env)->GetFieldID(env, cls, "fd", "I");
  if ((*env)->ExceptionCheck(env)) {
    (*env)->ExceptionClear(env);
  }
  return field;
}

__attribute__((visibility("default"))) jobject AFileDescriptor_create(JNIEnv *env) {
  jclass cls = (*env)->FindClass(env, "java/io/FileDescriptor");
  if (cls == NULL) {
    return NULL;
  }

  jmethodID ctor = (*env)->GetMethodID(env, cls, "<init>", "()V");
  if (ctor == NULL) {
    return NULL;
  }

  return (*env)->NewObject(env, cls, ctor);
}

__attribute__((visibility("default"))) int AFileDescriptor_getFd(JNIEnv *env, jobject file_descriptor) {
  if (file_descriptor == NULL) {
    return -1;
  }

  jclass cls = (*env)->GetObjectClass(env, file_descriptor);
  if (cls == NULL) {
    return -1;
  }

  jfieldID field = find_fd_field(env, cls);
  if (field == NULL) {
    return -1;
  }

  return (*env)->GetIntField(env, file_descriptor, field);
}

__attribute__((visibility("default"))) void AFileDescriptor_setFd(
    JNIEnv *env, jobject file_descriptor, int fd) {
  if (file_descriptor == NULL) {
    return;
  }

  jclass cls = (*env)->GetObjectClass(env, file_descriptor);
  if (cls == NULL) {
    return;
  }

  jfieldID field = find_fd_field(env, cls);
  if (field == NULL) {
    return;
  }

  (*env)->SetIntField(env, file_descriptor, field, fd);
}
