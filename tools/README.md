# 交叉编译工具链（本地自备，不入库）

Windows 版的构建脚本 `windows/build.sh` 需要一个本地 .NET 8 SDK 与 NuGet 引用程序集包：

```text
tools/dotnet/    # .NET 8 SDK（macOS 版本即可，交叉编译 net48）
tools/nuget/     # Microsoft.NETFramework.ReferenceAssemblies.net48 包
tools/home/      # DOTNET_CLI_HOME（运行时生成）
```

这些目录合计约 750 MB，**故意不放进仓库**。想自己构建 Windows 版时按以下方式补齐：

```bash
cd windows
# 1) 下载 .NET 8 SDK 解压到 ../tools/dotnet
# 2) 首次构建会自动从 NuGet 还原 net48 引用程序集到 ../tools/nuget
./build.sh
```

只想要现成安装包请直接下载 Releases 里的 zip，不需要这些工具链。
