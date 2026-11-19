#import "PythonHost.h"
#include <Python/Python.h>

@implementation PythonHost

static BOOL started = NO;

+ (void)startWithEnvironment:(NSDictionary<NSString *, NSString *> *)env onExit:(void (^)(int))onExit {
    if (started) return;
    started = YES;
    [env enumerateKeysAndObjectsUsingBlock:^(NSString *k, NSString *v, BOOL *stop) {
        setenv(k.UTF8String, v.UTF8String, 1);
    }];
    NSThread *t = [[NSThread alloc] initWithBlock:^{
        int code = [PythonHost run];
        dispatch_async(dispatch_get_main_queue(), ^{ onExit(code); });
    }];
    t.name = @"luna-backend";
    t.stackSize = 8 * 1024 * 1024;   // pydantic-core and the Director recurse deeper than a secondary thread's 512 KB
    t.qualityOfService = NSQualityOfServiceUserInitiated;
    [t start];
}

+ (int)run {
    NSString *res = [[NSBundle mainBundle] resourcePath];
    PyPreConfig pre;
    PyConfig config;
    PyPreConfig_InitIsolatedConfig(&pre);
    PyConfig_InitIsolatedConfig(&config);
    pre.utf8_mode = 1;
    config.buffered_stdio = 0;
    config.write_bytecode = 0;            // the bundle is signed and read-only
    config.install_signal_handlers = 0;   // the app owns signals; uvicorn runs off the main thread
    PyStatus st = Py_PreInitialize(&pre);
    if (PyStatus_Exception(st)) { NSLog(@"luna: Python pre-init failed: %s", st.err_msg); return 2; }
    NSString *home = [res stringByAppendingPathComponent:@"python"];
    wchar_t *w = Py_DecodeLocale(home.UTF8String, NULL);
    st = PyConfig_SetString(&config, &config.home, w);
    PyMem_RawFree(w);
    if (PyStatus_Exception(st)) { NSLog(@"luna: PYTHONHOME failed: %s", st.err_msg); PyConfig_Clear(&config); return 2; }
    st = PyConfig_Read(&config);
    if (PyStatus_Exception(st)) { NSLog(@"luna: Python config failed: %s", st.err_msg); PyConfig_Clear(&config); return 2; }
    st = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(st)) { NSLog(@"luna: Python init failed: %s", st.err_msg); return 2; }

    NSString *packages = [res stringByAppendingPathComponent:@"app_packages"];
    NSString *launcher = [res stringByAppendingPathComponent:@"app"];
    NSString *code = [NSString stringWithFormat:
        @"import site, sys\n"
         "site.addsitedir(%@)\n"
         "sys.path.insert(0, %@)\n"
         "import luna_ios\n"
         "_rc = luna_ios.main()\n",
        [PythonHost pyString:packages], [PythonHost pyString:launcher]];
    PyObject *main = PyImport_AddModule("__main__");
    PyObject *globals = PyModule_GetDict(main);
    PyObject *r = PyRun_String(code.UTF8String, Py_file_input, globals, globals);
    int rc = 1;
    if (r == NULL) {
        PyErr_Print();
    } else {
        Py_DECREF(r);
        PyObject *v = PyDict_GetItemString(globals, "_rc");
        if (v && PyLong_Check(v)) rc = (int)PyLong_AsLong(v);
    }
    NSLog(@"luna: backend exited with %d", rc);
    return rc;
}

/// A Python string literal for a path (repr-safe: backslashes and quotes escaped).
+ (NSString *)pyString:(NSString *)s {
    NSString *e = [[s stringByReplacingOccurrencesOfString:@"\\" withString:@"\\\\"]
                   stringByReplacingOccurrencesOfString:@"'" withString:@"\\'"];
    return [NSString stringWithFormat:@"'%@'", e];
}

@end
