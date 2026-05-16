# Flutter TDD — 進階 Widget 測試模式

## Pump 方法速查

| 方法 | 使用時機 |
|------|----------|
| `tester.pump()` | 推進一幀（觸發狀態變更後呼叫） |
| `tester.pumpAndSettle()` | 等待所有動畫與非同步工作完成 |
| `tester.pump(Duration(...))` | 推進指定時間長度 |

---

## 尋找 Widget

```dart
find.byType(CircularProgressIndicator)   // by widget type
find.byKey(Key('login_button'))          // by key (preferred for interaction)
find.text('Welcome back')                // by visible text
find.byIcon(Icons.email)                 // by icon
find.ancestor(of: ..., matching: ...)    // by ancestor
find.descendant(of: ..., matching: ...) // by descendant
```

---

## 與 Widget 互動

```dart
await tester.enterText(find.byKey(Key('email')), 'test@test.com');
await tester.tap(find.byType(ElevatedButton));
await tester.longPress(find.byKey(Key('item_0')));
await tester.drag(find.byType(ListView), Offset(0, -300));
await tester.fling(find.byType(Scrollable), Offset(0, -200), 800);
```

---

## 正確包裝受測 Widget

受測 widget 必須包裝在足夠的 context 中：

```dart
await tester.pumpWidget(
  MaterialApp(               // provides Directionality, Navigator, etc.
    home: Scaffold(
      body: MyWidget(),
    ),
  ),
);
```

BLoC 的包裝方式：

```dart
await tester.pumpWidget(
  MaterialApp(
    home: BlocProvider<MyBloc>.value(
      value: mockBloc,
      child: const MyPage(),
    ),
  ),
);
```

Riverpod 的包裝方式：

```dart
await tester.pumpWidget(
  ProviderScope(
    overrides: [myProvider.overrideWithValue(mockValue)],
    child: const MaterialApp(home: MyPage()),
  ),
);
```

---

## 測試非同步 Widget

```dart
testWidgets('loads data from network', (tester) async {
  when(() => mockRepo.fetchItems()).thenAnswer(
    (_) async {
      await Future.delayed(const Duration(milliseconds: 100));
      return Right(fakeItems);
    },
  );

  await tester.pumpWidget(/* ... */);

  // 初始顯示 loading
  expect(find.byType(CircularProgressIndicator), findsOneWidget);

  // 非同步完成後
  await tester.pumpAndSettle();
  expect(find.text('Item 1'), findsOneWidget);
});
```

---

## 測試導航（Navigation）

```dart
testWidgets('tapping logout navigates to LoginPage', (tester) async {
  final mockObserver = MockNavigatorObserver();

  await tester.pumpWidget(
    MaterialApp(
      navigatorObservers: [mockObserver],
      home: const HomePage(),
    ),
  );

  await tester.tap(find.byKey(const Key('logout_button')));
  await tester.pumpAndSettle();

  verify(() => mockObserver.didPush(any(), any())).called(1);
  expect(find.byType(LoginPage), findsOneWidget);
});
```

---

## 測試表單與驗證

```dart
testWidgets('shows error when email is empty', (tester) async {
  await tester.pumpWidget(/* LoginForm */);

  // Leave email empty, tap submit
  await tester.tap(find.byKey(const Key('submit_button')));
  await tester.pump();

  expect(find.text('Email is required'), findsOneWidget);
});

testWidgets('submit button disabled until form is valid', (tester) async {
  await tester.pumpWidget(/* LoginForm */);

  // Initially disabled
  final button = tester.widget<ElevatedButton>(find.byType(ElevatedButton));
  expect(button.onPressed, isNull);

  // After valid input
  await tester.enterText(find.byKey(Key('email')), 'valid@email.com');
  await tester.enterText(find.byKey(Key('password')), 'password123');
  await tester.pump();

  final updatedButton = tester.widget<ElevatedButton>(find.byType(ElevatedButton));
  expect(updatedButton.onPressed, isNotNull);
});
```

---

## 測試 Dialog 與 Snackbar

```dart
testWidgets('shows error snackbar on failure', (tester) async {
  whenListen(
    mockBloc,
    Stream.value(LoginFailure('Network error')),
    initialState: LoginInitial(),
  );

  await tester.pumpWidget(/* ... */);
  await tester.pump(); // trigger BlocListener

  expect(find.byType(SnackBar), findsOneWidget);
  expect(find.text('Network error'), findsOneWidget);
});
```

---

## 常見陷阱

### ❗ `pumpAndSettle` 在無限動畫時逾時

```dart
// 解法：改用指定時間長度的 pump
await tester.pump(const Duration(seconds: 1));
```

### ❗ 找不到 `MediaQuery`

```dart
// 解法：包裝在 MaterialApp 中，或手動加入 MediaQuery
MediaQuery(data: MediaQueryData(), child: MyWidget())
```

### ❗ 測試中出現 overflow 錯誤

```dart
// 解法：設定指定的畫面尺寸
await tester.binding.setSurfaceSize(const Size(400, 800));
addTearDown(() => tester.binding.setSurfaceSize(null));
```

### ❗ 有計時器的 widget（倒數計時、debounce）

```dart
// 解法：使用 FakeAsync（來自 package:fake_async 或 package:flutter_test）
fakeAsync((async) {
  // ... 觸發 widget 互動
  async.elapse(const Duration(seconds: 3));
  // ... 驗證結果
});
```
