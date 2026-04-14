# Flutter TDD — 架構與 DI 模式

## Clean Architecture 分層

```text
┌─────────────────────────────────┐
│       Presentation Layer        │  Widgets, BLoC/Cubit/Notifier
├─────────────────────────────────┤
│         Domain Layer            │  UseCases, Entities, Interfaces
├─────────────────────────────────┤
│          Data Layer             │  Repository impl, API, Local DB
└─────────────────────────────────┘
```

**依賴方向規則**：內層絕不依賴外層。Domain 層不知道 Flutter 或 HTTP 的存在。

---

## 依賴注入設定

### 使用 `get_it`（Service Locator 模式）

```dart
// lib/core/di/injection.dart
import 'package:get_it/get_it.dart';

final sl = GetIt.instance;

Future<void> configureDependencies() async {
  // Data sources
  sl.registerLazySingleton<AuthRemoteDataSource>(
    () => AuthRemoteDataSourceImpl(sl()),
  );

  // Repositories
  sl.registerLazySingleton<AuthRepository>(
    () => AuthRepositoryImpl(remoteDataSource: sl()),
  );

  // Use cases
  sl.registerFactory(() => LoginUseCase(sl()));

  // BLoC
  sl.registerFactory(
    () => LoginBloc(loginUseCase: sl()),
  );
}
```

在測試中改為注入 Mock：

```dart
setUp(() {
  sl.reset();
  sl.registerFactory<AuthRepository>(() => MockAuthRepository());
  sl.registerFactory(() => LoginUseCase(sl()));
});
```

### 使用 `injectable`（程式碼生成 DI）

```dart
@injectable
class LoginUseCase {
  final AuthRepository _repo;
  LoginUseCase(this._repo);  // injected automatically
}

@LazySingleton(as: AuthRepository)
class AuthRepositoryImpl implements AuthRepository { ... }
```

測試時透過 `@Injectable(env: [Environment.test])` 個別標記測試用實作：

```dart
// injectable v2 正確寫法
@InjectableInit
void configureDependencies() => getIt.init();

// 測試環境控制改由個別 registration 的 env 標記決定，例如：
// @Injectable(as: AuthRepository, env: [Environment.test])
// class FakeAuthRepository implements AuthRepository { ... }
```

---

## Repository 模式（可測試設計）

```dart
// domain/repositories/auth_repository.dart  (interface)
abstract class AuthRepository {
  Future<Either<Failure, User>> login(String email, String password);
  Future<Either<Failure, void>> logout();
}

// data/repositories/auth_repository_impl.dart  (implementation)
class AuthRepositoryImpl implements AuthRepository {
  final AuthRemoteDataSource _remote;
  AuthRepositoryImpl({required AuthRemoteDataSource remoteDataSource})
      : _remote = remoteDataSource;

  @override
  Future<Either<Failure, User>> login(String email, String password) async {
    try {
      final userModel = await _remote.login(email, password);
      return Right(userModel.toEntity());
    } on ServerException catch (e) {
      return Left(ServerFailure(e.message));
    }
  }
}
```

Unit test 時 Mock `AuthRemoteDataSource`，而非 Repository 本身。

---

## UseCase 模式

```dart
// One UseCase = one callable class
abstract class UseCase<Type, Params> {
  Future<Either<Failure, Type>> call(Params params);
}

class LoginUseCase implements UseCase<User, LoginParams> {
  final AuthRepository _repo;
  LoginUseCase(this._repo);

  @override
  Future<Either<Failure, User>> call(LoginParams params) =>
      _repo.login(params.email, params.password);
}

class LoginParams extends Equatable {
  final String email;
  final String password;
  const LoginParams({required this.email, required this.password});

  @override
  List<Object> get props => [email, password];
}
```

---

## Riverpod 替代方案

```dart
// Using AsyncNotifier (Riverpod 2.x)
@riverpod
class LoginNotifier extends _$LoginNotifier {
  @override
  AsyncValue<User?> build() => const AsyncData(null);

  Future<void> login(String email, String password) async {
    state = const AsyncLoading();
    final result = await ref.read(loginUseCaseProvider)(
      LoginParams(email: email, password: password),
    );
    state = result.fold(
      (failure) => AsyncError(failure, StackTrace.current),
      (user) => AsyncData(user),
    );
  }
}

// Test with ProviderContainer
test('login updates state to user', () async {
  final container = ProviderContainer(
    overrides: [
      // Riverpod 2.x 使用 overrideWith，overrideWithValue 已 deprecated
      loginUseCaseProvider.overrideWith(() => MockLoginUseCase()),
    ],
  );
  addTearDown(container.dispose);

  when(() => mockUseCase(any())).thenAnswer((_) async => Right(fakeUser));

  await container.read(loginNotifierProvider.notifier).login('e', 'p');

  expect(container.read(loginNotifierProvider), AsyncData(fakeUser));
});
```
