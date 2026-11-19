// Starts the embedded CPython (BeeWare Python.xcframework, PEP 730) on a background thread and runs ios/python/luna_ios.py:
// the Outpost Luna backend, in this process, on 127.0.0.1 only. docs/IPAD.md.
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface PythonHost : NSObject
/// Start the interpreter once. `env` is copied into the process environment first (LUNA_TOKEN, LUNA_SUPPORT, ...).
/// `onExit` runs on the main queue if the backend ever returns (a crash at start-up: the shell shows the error).
+ (void)startWithEnvironment:(NSDictionary<NSString *, NSString *> *)env onExit:(void (^)(int code))onExit;
@end

NS_ASSUME_NONNULL_END
