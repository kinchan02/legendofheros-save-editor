@echo off
rem 用默认浏览器打开本目录下的存档修改器（自动匹配 存档修改器*.html）
for %%f in ("%~dp0*.html") do start "" "%%~ff"
exit
