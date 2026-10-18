import sys
import fitdecode
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def extract_high_freq_accel(fit_path):
  x_vals, y_vals, z_vals = [], [], []
  printed_sample_fields = False

  with fitdecode.FitReader(fit_path) as fit:
    for frame in fit:
      if isinstance(frame, fitdecode.FitDataMessage):
        if frame.name in ["accelerometer_data", "sensor_data"]:
          # Inspect available field names once
          if not printed_sample_fields:
            field_names = [f.name for f in frame.fields if f.name]
            print(f"Detected fields in '{frame.name}': {field_names}")
            printed_sample_fields = True

          # Extract safely using has_field
          x = (
              frame.get_value("calibrated_accel_x")
              if frame.has_field("calibrated_accel_x")
              else (
                  frame.get_value("accel_x")
                  if frame.has_field("accel_x")
                  else (
                      frame.get_value("x") if frame.has_field("x") else None
                  )
              )
          )

          y = (
              frame.get_value("calibrated_accel_y")
              if frame.has_field("calibrated_accel_y")
              else (
                  frame.get_value("accel_y")
                  if frame.has_field("accel_y")
                  else (
                      frame.get_value("y") if frame.has_field("y") else None
                  )
              )
          )

          z = (
              frame.get_value("calibrated_accel_z")
              if frame.has_field("calibrated_accel_z")
              else (
                  frame.get_value("accel_z")
                  if frame.has_field("accel_z")
                  else (
                      frame.get_value("z") if frame.has_field("z") else None
                  )
              )
          )

          if x is not None and y is not None and z is not None:
            if isinstance(x, (list, tuple, np.ndarray)):
              x_vals.extend(x)
              y_vals.extend(y)
              z_vals.extend(z)
            else:
              x_vals.append(x)
              y_vals.append(y)
              z_vals.append(z)

  if not x_vals:
    return None

  df = pd.DataFrame({"x": x_vals, "y": y_vals, "z": z_vals})
  df["magnitude"] = np.sqrt(
      df["x"].astype(float) ** 2
      + df["y"].astype(float) ** 2
      + df["z"].astype(float) ** 2
  )
  return df


def main():
  fit_path = sys.argv[1] if len(sys.argv) > 1 else "real_pullups_7.fit"
  print(f"Reading: {fit_path}")

  df = extract_high_freq_accel(fit_path)
  if df is None or df.empty:
    print("Could not extract accelerometer arrays.")
    return

  print(f"Successfully loaded {len(df)} samples at 25Hz!")

  time_s = np.arange(len(df)) / 25.0

  fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)

  axes[0].plot(time_s, df["x"], label="Accel X", color="red", lw=1)
  axes[0].set_ylabel("X (mG)")
  axes[0].grid(True)
  axes[0].legend(loc="upper right")

  axes[1].plot(time_s, df["y"], label="Accel Y", color="green", lw=1)
  axes[1].set_ylabel("Y (mG)")
  axes[1].grid(True)
  axes[1].legend(loc="upper right")

  axes[2].plot(time_s, df["z"], label="Accel Z", color="blue", lw=1)
  axes[2].set_ylabel("Z (mG)")
  axes[2].grid(True)
  axes[2].legend(loc="upper right")

  axes[3].plot(
      time_s, df["magnitude"], label="Magnitude", color="black", lw=1.2
  )
  axes[3].set_ylabel("Magnitude (mG)")
  axes[3].set_xlabel("Time (seconds)")
  axes[3].grid(True)
  axes[3].legend(loc="upper right")

  plt.suptitle(
      f"Garmin FR165 - High-Frequency (25Hz) Pull-Up Data ({len(df)} samples)",
      fontsize=14,
  )
  plt.tight_layout()
  plt.show()


if __name__ == "__main__":
  main()