# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd


def read_xdf(filename):
    """**Read and tidy an XDF file**

    Reads and tidies an XDF file with multiple streams into a Pandas DataFrame.
    The function outputs both the dataframe and the information (such as the sampling rate).

    Note that, as XDF can store streams with different sampling rates and different time stamps,
    **the function will resample all streams to 2 times the highest sampling rate** (to minimize
    aliasing). The final sampling rate can be found in the ``info`` dictionary.

    .. note::

        This function requires the *pyxdf* module to be installed. You can install it with
        ``pip install pyxdf``.

    Parameters
    ----------
    filename :  str
        Path (with the extension) of an XDF file (e.g., ``"data.xdf"``).

    Returns
    ----------
    df : DataFrame, dict
        The BITalino file as a pandas dataframe if one device was read, or a dictionary
        of pandas dataframes (one dataframe per device) if multiple devices are read.
    info : dict
        The metadata information containing the sampling rate(s).

    See Also
    --------
    .read_bitalino, .signal_resample

    Examples
    --------
    .. ipython:: python

      import neurokit2 as nk

      # data, info = nk.read_xdf("data.xdf")
      # sampling_rate = info["sampling_rate"]
    """
    try:
        import pyxdf
    except ImportError:
        raise ImportError(
            "The 'pyxdf' module is required for this function to run. ",
            "Please install it first (`pip install pyxdf`).",
        )

    # Load file
    # TODO: would be nice to be able to stream a file from URL
    streams, header = pyxdf.load_xdf(filename)

    # Get smaller time stamp to later use as offset (zero point)
    min_ts = min([min(s["time_stamps"]) for s in streams])

    # Loop through all the streams and convert to dataframes
    dfs = []
    for stream in streams:
        # Get columns names and make dataframe
        channels_info = stream["info"]["desc"][0]["channels"][0]["channel"]
        cols = [channels_info[i]["label"][0] for i in range(len(channels_info))]
        dat = pd.DataFrame(stream["time_series"], columns=cols)

        # Special treatment for some devices
        if stream["info"]["name"][0] == "Muse":
            # Rename GYRO channels and add ACCelerometer
            if stream["info"]["type"][0] == "GYRO":
                dat = dat.rename(columns={"X": "GYRO_X", "Y": "GYRO_Y", "Z": "GYRO_Z"})
                dat["ACC"] = np.sqrt(
                    dat["GYRO_X"] ** 2 + dat["GYRO_Y"] ** 2 + dat["GYRO_Z"] ** 2
                )

            # Muse - PPG data has three channels: ambient, infrared, red
            if stream["info"]["type"][0] == "PPG":
                dat["PPG2"] = dat["PPG2"].replace(0, value=np.nan)
                dat = dat.rename(columns={"PPG1": "LUX", "PPG2": "PPG", "PPG3": "RED"})

        # Get time stamps and offset from minimum time stamp
        dat["timestamps"] = pd.to_datetime(stream["time_stamps"] - min_ts, unit="s")
        dfs.append(dat)

    # Store info of each stream ----------------------------------------------------------------

    # Store metadata
    info = {
        "sampling_rates_original": [
            float(s["info"]["nominal_srate"][0]) for s in streams
        ],
        "sampling_rates_effective": [
            float(s["info"]["effective_srate"]) for s in streams
        ],
        "datetime": header["info"]["datetime"][0],
        "data": dfs,
    }

    # Synchronize ------------------------------------------------------------------------------
    # Merge all dataframes by timestamps
    # Note: this is a critical steps, as it inserts timestamps and makes it non-evenly spread
    df = dfs[0]
    for i in range(1, len(dfs)):
        df = pd.merge(df, dfs[i], how="outer").sort_values(by="timestamps")

    # Final sampling rate will be 2 times the maximum sampling rate
    # (to minimize aliasing during interpolation)
    info["sampling_rate"] = int(np.max(info["sampling_rates_original"]) * 2)

    # Resample and Interpolate -----------------------------------------------------------------
    df = df.set_index("timestamps")
    # pandas requires the SR in "ms"
    df = df.resample(str(1000 / info["sampling_rate"]) + "ms").bfill()
    # Interpolate (but leave holes longer than 1 second)
    df = df.interpolate(method="linear", limit=info["sampling_rate"])

    return df, info
