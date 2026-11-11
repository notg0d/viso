// Shared by Setup and Uninstall, and exercised by the non-installing launch probe.
function ExecNativePowerShell(const Parameters: String; var ExitCode: Integer): Boolean;
begin
#if Ver >= 0x07000000
  // Inno 7 Exec no longer disables WOW64 redirection in 64-bit install mode.
  // This API supports both 32-bit and 64-bit Setup/Uninstall engines.
  Result := ExecWithNativeSysDir(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
#else
  // Inno 6 Exec disables WOW64 redirection in our required 64-bit install mode.
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
#endif
end;
