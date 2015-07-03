::Install 32 bit openssl.  Expects tar file in cwd. We delete the openssl dir to
::avoid any 32-64 contamination.
call C:\grr\vagrant\windows\32bitenv.bat
cd %SYSTEMDRIVE%\openssl
rd /q /s openssl-1.0.2c
7z x openssl-1.0.2c.tar
cd openssl-1.0.2c
perl Configure VC-WIN32 --prefix=C:\Build-OpenSSL-VC-32
call ms\do_nasm.bat
nmake -f ms\ntdll.mak
nmake -f ms\ntdll.mak install
cd %USERPROFILE%
xcopy C:\Build-OpenSSL-VC-32\bin\*.dll C:\PYTHON_32\libs\ /e /h /y

:: M2Crypto expects the openssl pieces to be here.  Theoretically you should be
:: able to do:
:: python setup.py build_ext --openssl="C:\Build-OpenSSL-VC-32"
:: python setup.py build
:: python setup.py install
:: But I could never get this to work, it built fine but would always fail to
:: import the DLLs later.
rd /q /s C:\pkg
xcopy C:\Build-OpenSSL-VC-32\include C:\pkg\include\ /s /e /h /y
xcopy C:\Build-OpenSSL-VC-32\lib C:\pkg\lib\ /s /e /h /y

pip install git+https://github.com/M2Crypto/M2Crypto.git@73f8d71c021a547d435753985cb45ed8d6c7c845#egg=M2Crypto
rd /q /s C:\pkg
python -c "import M2Crypto" || echo "32bit M2Crypto install failed" && exit /b 1


