function demo_matlab(task_id)
%DEMO_MATLAB  Baobab HPC demo (MATLAB, no toolbox needed).
%   Analyses the synthetic sessions in ../demo_data: dF/F, event detection,
%   event rates and stimulus-triggered responses. Writes, per session, a CSV
%   summary and a PNG figure into the results folder.
%
%   demo_matlab           analyses every session
%   demo_matlab(task_id)  analyses one session - this is how a job array
%                         calls it (array range 1-4)
%
%   On Baobab, BAOBAB_DATA / BAOBAB_RESULTS point to the job's data and
%   results folders. Locally, it uses ../demo_data and ./results.
%
%   Checkpoints: the sessions already analysed are recorded in
%   BAOBAB_CHECKPOINT_DIR. When the file named by BAOBAB_TIME_UP appears
%   (shortly before the time limit), the function stops and exits with code 3;
%   with "Continue automatically" ticked, the next run skips the finished
%   sessions. To try it, set SECONDS_PER_SESSION = 120 below and submit with a
%   wall time of 00:05:00.

SECONDS_PER_SESSION = 0;           % set to 120 to try automatic continuation (see above)
if ~isempty(getenv('DEMO_SECONDS_PER_SESSION'))
    SECONDS_PER_SESSION = str2double(getenv('DEMO_SECONDS_PER_SESSION'));
end
CONTINUE_LATER = 3;                % exit code: "checkpoint saved, run me again"

here = fileparts(mfilename('fullpath'));
addpath(fullfile(here, 'utils'));              % on Baobab the app adds it too

data_dir = getenv('BAOBAB_DATA');
if isempty(data_dir), data_dir = fullfile(here, '..', 'demo_data'); end
out_dir = getenv('BAOBAB_RESULTS');
if isempty(out_dir), out_dir = fullfile(here, 'results'); end
if ~exist(out_dir, 'dir'), mkdir(out_dir); end

files = dir(fullfile(data_dir, 'session_*.csv'));
if isempty(files), error('No session_*.csv found in %s', data_dir); end
names = sort({files.name});
if nargin >= 1                                 % job array: one session per task
    want = sprintf('session_%02d.csv', task_id);
    names = names(strcmp(names, want));
    if isempty(names), error('No session number %d in %s', task_id, data_dir); end
end

onsets = read_csv_numeric(fullfile(data_dir, 'stimulus_onsets.csv'));

% checkpoint: which sessions are already done (kept between the runs of a job
% on Baobab; a local run always starts from scratch)
ckpt_dir = getenv('BAOBAB_CHECKPOINT_DIR');
progress = '';
if ~isempty(ckpt_dir)
    if nargin >= 1
        progress = fullfile(ckpt_dir, sprintf('demo_progress_%d.txt', task_id));
    else
        progress = fullfile(ckpt_dir, 'demo_progress.txt');
    end
end
done = {};
if ~isempty(progress) && exist(progress, 'file')
    done = strsplit(strtrim(fileread(progress)));
end
if exist('maxNumCompThreads') %#ok<EXIST>
    nthreads = maxNumCompThreads;
else
    nthreads = 1;                              % GNU Octave
end
fprintf('MATLAB %s, %d thread(s); data: %s\n', version, nthreads, data_dir);

for k = 1:numel(names)
    [~, name] = fileparts(names{k});
    if any(strcmp(done, name))
        fprintf('%s: done in an earlier run - skipped\n', name);
        continue
    end
    if time_up()
        fprintf('Time is almost up: %d of %d session(s) done, the next run continues from here\n', ...
                numel(done), numel(names));
        exit(CONTINUE_LATER);
    end
    tic;
    table = read_csv_numeric(fullfile(data_dir, names{k}));
    t = table(:, 1);
    traces = table(:, 2:end);
    fs = 1 / median(diff(t));

    dff = delta_f_over_f(traces);
    events = detect_events(dff, fs);
    rates = cellfun(@numel, events) / (t(end) - t(1));
    [axis_s, avg] = triggered_average(dff, t, onsets);
    base = mean(avg(axis_s < 0, :), 1);
    response = max(avg(axis_s > 0 & axis_s < 1.5, :), [], 1) - base;

    % summary table
    fid = fopen(fullfile(out_dir, [name '_summary.csv']), 'w');
    fprintf(fid, 'cell,event_rate_hz,mean_dff,stim_response_dff\n');
    for c = 1:size(traces, 2)
        fprintf(fid, '%d,%.4f,%.4f,%.4f\n', c, rates(c), mean(dff(:, c)), response(c));
    end
    fclose(fid);

    % figure (drawn off-screen: there is no display on the cluster)
    try
        f = figure('Visible', 'off', 'Position', [0 0 1100 450]);
        subplot(1, 3, [1 2]);
        imagesc(t, 1:size(dff, 2), dff');
        caxis([0 max(dff(:)) * 0.9]);
        colormap(hot);
        colorbar;
        hold on;
        for on = onsets(:)'
            plot([on on], [0.5 size(dff, 2) + 0.5], 'c-');
        end
        xlabel('time (s)'); ylabel('cell');
        title(sprintf('%s: dF/F (cyan = stimulus)', strrep(name, '_', '\_')));
        subplot(1, 3, 3);
        bar(1:numel(response), response);
        xlabel('cell'); ylabel('peak dF/F after stimulus'); title('stimulus response');
        print(f, fullfile(out_dir, [name '_overview.png']), '-dpng', '-r120');
        close(f);
    catch err
        warning('demo:figure', 'Figure not saved: %s', err.message);
    end

    if SECONDS_PER_SESSION > 0
        pause(SECONDS_PER_SESSION);            % pretend the analysis is long
    end
    done{end + 1} = name; %#ok<AGROW>
    if ~isempty(progress)                      % checkpoint after each session
        fid = fopen(progress, 'w');
        fprintf(fid, '%s\n', done{:});
        fclose(fid);
    end

    fprintf('%s: %d events, %d responsive cells, %.1f s\n', name, ...
            sum(cellfun(@numel, events)), sum(response > 0.3), toc);
end
fprintf('Results written to %s\n', out_dir);
end


function up = time_up()
%TIME_UP  True once Baobab has warned that the time limit is close.
flag = getenv('BAOBAB_TIME_UP');
up = ~isempty(flag) && exist(flag, 'file') == 2;
end


function M = read_csv_numeric(file)
%READ_CSV_NUMERIC  Numeric CSV with one header line (MATLAB and Octave).
if exist('readmatrix') %#ok<EXIST>
    M = readmatrix(file);
else
    M = dlmread(file, ',', 1, 0);
end
end
