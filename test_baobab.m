function test_baobab
    fprintf('Hello from %s\n', getenv('HOSTNAME'));
    x = rand(1000);
    fprintf('Sum = %.2f\n', sum(x(:)));
    if ~exist('results','dir'), mkdir('results'); end
    save('results/test_output.mat','x');
end