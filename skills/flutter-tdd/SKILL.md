---
name: flutter-tdd
type: know
description: >
  Flutter 行動應用的測試驅動開發（TDD）專家指引。
  適用情境：用戶詢問 Flutter 測試、TDD 工作流程、unit/widget/integration test 撰寫、
  mock 依賴、BLoC/Riverpod/Clean Architecture 可測試性設計、golden test、
  測試覆蓋率、Flutter CI/CD 設定。
  觸發關鍵字：「flutter test」、「tdd flutter」、「widget test」、「mockito flutter」、
  「bloc_test」、「integration test flutter」、「flutter 怎麼測試」、「Flutter 測試策略」、
  「flutter unit test」、「flutter golden test」。
  當用戶貼上 Flutter 程式碼並詢問如何讓它可測試時，也應觸發此 Skill。
---

# Flutter TDD 技能指引

提供 Flutter 行動應用的 TDD 方法論、模式、最佳實踐與程式碼範例。

---

## 快速參考

| 層級 | 測試類型 | 主要工具 |
|------|----------|----------|
| Domain / Data | Unit Test | `flutter_test`、`mockito`、`mocktail` |
| Presentation | Widget Test | `flutter_test`、`bloc_test` |
| 完整應用流程 | Integration Test | `integration_test`（官方） |
| 視覺回歸 | Golden Test | `golden_toolkit` |

---

## 推薦套件

```yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  mockito: ^5.4.4          # Mock generation (requires build_runner)
  mocktail: ^1.0.3         # Mock without code gen (simpler)
  bloc_test: ^9.1.7        # BLoC / Cubit test helpers
  build_runner: ^2.4.9     # Code generation for mockito
  integration_test:
    sdk: flutter
  golden_toolkit: ^0.15.0  # Golden / screenshot tests
```

> **建議**：小型專案優先選 `mocktail`（不需 code gen）。大型團隊需要嚴格型別檢查時，改用 `mockito` + `build_runner`。

---

## 可測試架構設計

TDD 必須搭配 **Clean Architecture** + 依賴注入：

```text
lib/
├── core/            # DI container, errors, utils
├── data/            # Repository implementations, API clients, local DB
├── domain/          # Entities, UseCases, repository interfaces
└── presentation/    # Widgets, BLoC / Cubit / Riverpod Notifiers

test/
├── data/
├── domain/
└── presentation/
```

黃金法則：**每個依賴都必須可注入**，才能在測試中替換成 Mock。

詳細架構模式 → 參見 `references/architecture.md`

---

## TDD 循環：Red → Green → Refactor

### Step 1 — RED：先寫一個失敗的測試

```dart
// test/domain/login_usecase_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockAuthRepository extends Mock implements AuthRepository {}

void main() {
  late MockAuthRepository mockRepo;
  late LoginUseCase loginUseCase;

  setUp(() {
    mockRepo = MockAuthRepository();
    loginUseCase = LoginUseCase(mockRepo);
  });

  test('returns User when credentials are valid', () async {
    // Arrange
    when(() => mockRepo.login('email@test.com', 'pass123'))
        .thenAnswer((_) async => Right(fakeUser));

    // Act
    final result = await loginUseCase('email@test.com', 'pass123');

    // Assert
    expect(result, Right(fakeUser));
    verify(() => mockRepo.login('email@test.com', 'pass123')).called(1);
  });

  test('returns Failure when credentials are invalid', () async {
    when(() => mockRepo.login(any(), any()))
        .thenAnswer((_) async => Left(AuthFailure('Invalid credentials')));

    final result = await loginUseCase('bad@email.com', 'wrong');

    expect(result, isA<Left<AuthFailure, User>>());
  });
}
```

### Step 2 — GREEN：實作最少量程式碼使測試通過

```dart
// lib/domain/usecases/login_usecase.dart
class LoginUseCase {
  final AuthRepository _repo;
  LoginUseCase(this._repo);

  Future<Either<Failure, User>> call(String email, String password) =>
      _repo.login(email, password);
}
```

### Step 3 — REFACTOR：在測試保持綠燈的情況下整理程式碼

---

## Widget 測試

測試 UI 行為，不測試實作細節。

Widget 測試中使用 `MockBloc` 時，**必須繼承 `MockBloc<Event, State>`**，不可用裸 `Mock`；
`BlocProvider` 內部需要 `stream` 與 `state` getter，裸 `Mock` 不提供這些。

```dart
// 正確宣告方式（bloc_test v9+）
class MockLoginBloc extends MockBloc<LoginEvent, LoginState>
    implements LoginBloc {}
```

```dart
// test/presentation/login_page_test.dart
testWidgets('shows loading indicator while logging in', (tester) async {
  // Arrange
  final mockBloc = MockLoginBloc();
  whenListen(
    mockBloc,
    Stream.fromIterable([LoginLoading()]),
    initialState: LoginInitial(),
  );

  // Act
  await tester.pumpWidget(
    MaterialApp(
      home: BlocProvider<LoginBloc>.value(
        value: mockBloc,
        child: const LoginPage(),
      ),
    ),
  );
  await tester.pump();

  // Assert
  expect(find.byType(CircularProgressIndicator), findsOneWidget);
});

testWidgets('navigates to Home on successful login', (tester) async {
  final mockBloc = MockLoginBloc();
  whenListen(
    mockBloc,
    Stream.fromIterable([LoginSuccess(fakeUser)]),
    initialState: LoginInitial(),
  );

  await tester.pumpWidget(/* ... */);
  await tester.pumpAndSettle();

  expect(find.byType(HomePage), findsOneWidget);
});
```

完整 widget 測試模式 → 參見 `references/widget-testing.md`

---

## BLoC / Cubit 測試

> **前提條件**：`blocTest` 的 `expect` 使用物件比較，State class **必須實作 value equality**（繼承 `Equatable` 或覆寫 `==` 與 `hashCode`）。若 State 是普通 class，`expect` 永遠失敗且錯誤訊息不明確。

```dart
// test/presentation/login_bloc_test.dart
blocTest<LoginBloc, LoginState>(
  'emits [Loading, Success] when login succeeds',
  build: () {
    when(() => mockLoginUseCase(any(), any()))
        .thenAnswer((_) async => Right(fakeUser));
    return LoginBloc(loginUseCase: mockLoginUseCase);
  },
  act: (bloc) => bloc.add(LoginSubmitted('email@test.com', 'pass')),
  expect: () => [LoginLoading(), LoginSuccess(fakeUser)],
);

blocTest<LoginBloc, LoginState>(
  'emits [Loading, Failure] when login fails',
  build: () {
    when(() => mockLoginUseCase(any(), any()))
        .thenAnswer((_) async => Left(AuthFailure('error')));
    return LoginBloc(loginUseCase: mockLoginUseCase);
  },
  act: (bloc) => bloc.add(LoginSubmitted('bad@email.com', 'wrong')),
  expect: () => [LoginLoading(), LoginFailure('error')],
);
```

---

## 整合測試

只涵蓋關鍵使用者流程，放在 `integration_test/` 目錄：

```dart
// integration_test/login_flow_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:my_app/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('complete login flow', (tester) async {
    app.main();
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('email_field')), 'user@test.com');
    await tester.enterText(find.byKey(const Key('password_field')), 'secret');
    await tester.tap(find.byKey(const Key('login_button')));
    await tester.pumpAndSettle();

    expect(find.text('Welcome'), findsOneWidget);
  });
}
```

執行指令：`flutter test integration_test/`

---

## Golden 測試（視覺回歸）

```dart
testWidgets('LoginButton matches golden', (tester) async {
  await loadAppFonts(); // from golden_toolkit

  await tester.pumpWidgetBuilder(
    const LoginButton(enabled: true),
    surfaceSize: const Size(300, 60),
  );

  await expectLater(
    find.byType(LoginButton),
    matchesGoldenFile('goldens/login_button_enabled.png'),
  );
});
```

更新 golden 基準圖：`flutter test --update-goldens`

---

## 最佳實踐

### ✅ 命名慣例

```text
[UnitUnderTest]_[Scenario]_[ExpectedResult]
loginUseCase_withValidCredentials_returnsUser
```

### ✅ 每個測試都遵循 AAA 結構

```dart
// Arrange — set up state and mocks
// Act     — call the unit under test
// Assert  — verify the outcome
```

### ✅ 測試行為，不測試實作細節

```dart
// ❌ 脆弱：測試內部狀態
expect(bloc.isLoading, true);

// ✅ 穩健：測試可觀察的結果
expect(find.byType(CircularProgressIndicator), findsOneWidget);
```

### ✅ 用 `setUp` / `tearDown` 管理共享狀態

```dart
setUp(() {
  mockRepo = MockAuthRepository();
  useCase = LoginUseCase(mockRepo);
});
```

### ✅ 保持測試快速且隔離

- Unit test 應在毫秒內完成
- Unit test 與 widget test 中絕不呼叫真實網路或資料庫
- 時間相關邏輯使用 `FakeAsync`

### ✅ 覆蓋率目標

- Domain 層：目標 > 90%
- Presentation 層：目標 > 70%
- 整體專案：目標 > 80%

---

## CI/CD 設定（GitHub Actions）

```yaml
# .github/workflows/flutter_test.yml
name: Flutter Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.x'
      - run: flutter pub get
      - run: flutter test --coverage
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage/lcov.info
```

---

## 常見情境快速參考

| 情境 | 解法 |
|------|------|
| Mock HTTP client | Mock Repository — unit test 中不直接測試 HTTP |
| 偽造 SharedPreferences | `SharedPreferences.setMockInitialValues({})` |
| 測試 Stream / Rx | `expectLater(stream, emitsInOrder([...]))` |
| 測試導航 | `MockNavigatorObserver` + `verify(mockObserver.didPush(...))` |
| 測試錯誤處理 | 同時測試 `Either` 的 `Right` 與 `Left` 分支 |
| 測試計時器 / 延遲 | `FakeAsync`（來自 `package:fake_async`） |
| 測試表單驗證 | `tester.enterText` + 檢查錯誤提示 widget |

---

## 參考文件

- `references/architecture.md` — Clean Architecture 設定與 DI 模式
- `references/widget-testing.md` — 進階 widget 測試模式與常見陷阱
